"""
pipeline.py — Wraps the run.py pipeline for GUI integration.

Runs the conversion in a background thread, reporting progress and log
messages back to the GUI via callbacks.  The GUI polls a queue to pick
up these messages without blocking the tkinter event loop.

Usage (from gui.py):
    from pipeline import PipelineRunner
    runner = PipelineRunner(log_callback, progress_callback, done_callback)
    runner.start_full(pdf_path, template, output_path, page_range, save_raw)
    runner.start_postprocess(raw_path, pdf_path, template, output_path, page_range)
"""

import io
import sys
import threading
import traceback
from pathlib import Path
from typing import Callable, Optional

from config import MARKER_PDF_DIR


# ── Ensure marker-pdf is importable ──────────────────────────────────────

def _ensure_import_path():
    """Add marker-pdf/ to sys.path so we can `import run`."""
    mp = str(MARKER_PDF_DIR)
    if mp not in sys.path:
        sys.path.insert(0, mp)


# ── Stdout capture ─────────────────────────────────────────────────────

class _LogCapture(io.TextIOBase):
    """
    A file-like object that intercepts writes (from print() in run.py)
    and forwards them to a callback function.  Also writes to the real
    stdout so terminal debugging still works during development.
    """
    def __init__(self, callback: Callable[[str], None], real_stdout):
        self._callback = callback
        self._real = real_stdout

    def write(self, text: str) -> int:
        if text and text.strip():
            self._callback(text.rstrip("\n"))
        if self._real:
            self._real.write(text)
        return len(text)

    def flush(self):
        if self._real:
            self._real.flush()


# ── Pipeline runner ────────────────────────────────────────────────────

class PipelineRunner:
    """
    Manages a single pipeline run in a background thread.

    Callbacks (all called from the background thread — the GUI must use
    root.after() or a queue to marshal them onto the main thread):

        log_callback(message: str)
            A line of text for the log pane.

        progress_callback(fraction: float, label: str)
            fraction: 0.0–1.0 progress value
            label: short description of the current step

        done_callback(success: bool, output_path: str | None, error: str | None)
            Called when the run completes or fails.
    """

    def __init__(
        self,
        log_callback: Callable[[str], None],
        progress_callback: Callable[[float, str], None],
        done_callback: Callable[[bool, Optional[str], Optional[str]], None],
    ):
        self._log = log_callback
        self._progress = progress_callback
        self._done = done_callback
        self._thread: Optional[threading.Thread] = None
        self._cancelled = False

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def cancel(self):
        """Request cancellation (checked between pipeline steps)."""
        self._cancelled = True

    # ── Public entry points ────────────────────────────────────────────

    def start_full(
        self,
        pdf_path: str,
        template: str,
        output_path: str,
        page_range: str = "",
        save_raw: bool = False,
    ):
        """Start a full conversion (Marker ML + post-processing)."""
        self._cancelled = False
        self._thread = threading.Thread(
            target=self._run_full,
            args=(pdf_path, template, output_path, page_range, save_raw),
            daemon=True,
        )
        self._thread.start()

    def start_postprocess(
        self,
        raw_path: str,
        pdf_path: str,
        template: str,
        output_path: str,
        page_range: str = "",
    ):
        """Start a post-process-only run (no Marker, just font maps + passes)."""
        self._cancelled = False
        self._thread = threading.Thread(
            target=self._run_postprocess,
            args=(raw_path, pdf_path, template, output_path, page_range),
            daemon=True,
        )
        self._thread.start()

    # ── Internal: full conversion ──────────────────────────────────────

    def _run_full(self, pdf_path, template, output_path, page_range_str, save_raw):
        _ensure_import_path()
        old_stdout = sys.stdout
        sys.stdout = _LogCapture(self._log, old_stdout)
        try:
            import run

            pp = Path(pdf_path)
            op = Path(output_path)

            # Step 1: Load template
            self._step(0.02, "Loading template config...")
            cfg = run.load_template(template)
            self._log(f"Template: {template}")

            # Load question config
            qcfg = self._load_questions(template, run)

            # Parse page range
            pr = self._parse_page_range(page_range_str)

            if self._cancelled:
                self._done(False, None, "Cancelled"); return

            # Step 2: Detect body font
            self._step(0.05, "Detecting body font...")
            bfn, bs = run.detect_body_font(pp, pr)
            self._log(f"Body font: {bfn} @ {bs}pt")

            if self._cancelled:
                self._done(False, None, "Cancelled"); return

            # Step 3: Build font maps
            self._step(0.08, "Building font maps...")
            hm, ho, ss, bq, ci, vm, ct, ib, vs = self._build_font_maps(
                run, pp, cfg, bs, pr
            )

            if self._cancelled:
                self._done(False, None, "Cancelled"); return

            # Step 4: Load ML models
            self._step(0.25, "Loading ML models (may download on first run)...")
            run.patch_block_relabel()

            import torch
            from marker.models import create_model_dict
            models = create_model_dict(device="cpu", dtype=torch.float32)
            self._log(f"Models loaded: {list(models.keys())}")

            if self._cancelled:
                self._done(False, None, "Cancelled"); return

            # Step 5: Marker conversion
            self._step(0.35, "Running Marker PDF extraction (this takes a while)...")
            import os
            from marker.converters.pdf import PdfConverter

            mcfg = {
                "lowres_image_dpi": 96,
                "block_relabel_str": "SectionHeader:Text:0.6,Figure:Text:1.0,Picture:Text:1.0",
                "level_count": 4, "default_level": 3,
                "common_element_threshold": 0.15, "text_match_threshold": 85,
                "BlockquoteProcessor_min_x_indent": 0.01,
                "BlockquoteProcessor_x_start_tolerance": 0.05,
                "BlockquoteProcessor_x_end_tolerance": 0.05,
                "TextProcessor_column_gap_ratio": 0.06,
                "disable_links": True, "disable_ocr": True, "pdftext_workers": 1,
                "disable_image_extraction": True, "extract_images": False,
            }

            # Gemini LLM (optional)
            gak = os.environ.get("GOOGLE_API_KEY", "")
            llm = None
            if gak:
                mn = run.get_available_gemini_model(gak)
                mcfg["gemini_api_key"] = gak
                mcfg["gemini_model_name"] = mn
                llm = "marker.services.gemini.GoogleGeminiService"
                self._log(f"LLM enabled: {mn}")
            else:
                self._log("LLM disabled: no GOOGLE_API_KEY")

            if pr:
                mcfg["page_range"] = pr

            conv = PdfConverter(
                artifact_dict=models, processor_list=None,
                config=mcfg, llm_service=llm,
            )
            rendered = conv(str(pp))

            if save_raw:
                rp = op.with_suffix(".raw.md")
                rp.write_text(rendered.markdown, encoding="utf-8")
                self._log(f"Raw saved: {rp}")

            if self._cancelled:
                self._done(False, None, "Cancelled"); return

            # Step 6: Post-processing
            self._step(0.90, "Post-processing...")
            md = run.post_process(
                rendered.markdown, hm, ss, bq, ci, vm, cfg,
                ct, ib, ho, vs, questions_cfg=qcfg,
            )

            op.write_text(md, encoding="utf-8")
            self._step(1.0, "Done!")
            self._log(f"Output: {op} ({len(md.splitlines())} lines)")
            self._done(True, str(op), None)

        except Exception as e:
            self._log(f"ERROR: {e}")
            self._log(traceback.format_exc())
            self._done(False, None, str(e))
        finally:
            sys.stdout = old_stdout

    # ── Internal: post-process only ─────────────────────────────────────

    def _run_postprocess(self, raw_path, pdf_path, template, output_path, page_range_str):
        _ensure_import_path()
        old_stdout = sys.stdout
        sys.stdout = _LogCapture(self._log, old_stdout)
        try:
            import run

            rp = Path(raw_path)
            pp = Path(pdf_path)
            op = Path(output_path)

            # Step 1: Load template
            self._step(0.02, "Loading template config...")
            cfg = run.load_template(template)
            self._log(f"Template: {template}")

            qcfg = self._load_questions(template, run)
            pr = self._parse_page_range(page_range_str)

            if self._cancelled:
                self._done(False, None, "Cancelled"); return

            # Step 2: Detect body font
            self._step(0.08, "Detecting body font...")
            bfn, bs = run.detect_body_font(pp, pr)
            self._log(f"Body font: {bfn} @ {bs}pt")

            if self._cancelled:
                self._done(False, None, "Cancelled"); return

            # Step 3: Build font maps
            self._step(0.15, "Building font maps...")
            hm, ho, ss, bq, ci, vm, ct, ib, vs = self._build_font_maps(
                run, pp, cfg, bs, pr
            )

            if self._cancelled:
                self._done(False, None, "Cancelled"); return

            # Step 4: Post-process
            self._step(0.50, "Post-processing...")
            raw = rp.read_text(encoding="utf-8")
            md = run.post_process(
                raw, hm, ss, bq, ci, vm, cfg,
                ct, ib, ho, vs, questions_cfg=qcfg,
            )

            op.write_text(md, encoding="utf-8")
            self._step(1.0, "Done!")
            self._log(f"Output: {op} ({len(md.splitlines())} lines)")
            self._done(True, str(op), None)

        except Exception as e:
            self._log(f"ERROR: {e}")
            self._log(traceback.format_exc())
            self._done(False, None, str(e))
        finally:
            sys.stdout = old_stdout

    # ── Shared helpers ─────────────────────────────────────────────────────

    def _step(self, fraction: float, label: str):
        self._progress(fraction, label)
        self._log(label)

    def _parse_page_range(self, page_range_str: str) -> Optional[list[int]]:
        pr_str = page_range_str.strip()
        if not pr_str:
            return None
        pages = []
        for part in pr_str.split(","):
            part = part.strip()
            if "-" in part:
                s, e = part.split("-", 1)
                pages.extend(range(int(s), int(e) + 1))
            else:
                pages.append(int(part))
        return pages

    def _load_questions(self, template, run_module):
        from config import MARKER_PDF_DIR
        qpath = MARKER_PDF_DIR / "templates" / template / "questions_final.yaml"
        if qpath.exists():
            qd = run_module._load_yaml(qpath)
            qcfg = qd.get("questions", [])
            self._log(f"Questions config: {len(qcfg)} entries")
            return qcfg
        return None

    def _build_font_maps(self, run, pp, cfg, bs, pr):
        """Build all font maps and return them as a tuple."""
        hm, ho = run.build_heading_map(pp, cfg, bs, pr)
        ss = run.build_skip_set(pp, cfg, bs, pr)
        bq, ci = run.build_blockquote_set(pp, cfg, bs, pr)
        vm = run.build_verse_map(pp, cfg, bs, pr)
        ct = run.build_callout_set(pp, cfg, bs, pr)
        ib = run.build_inline_bold_set(pp, cfg, bs, pr)
        cfg["_rotated_subdivisions"] = run.build_rotated_subdivisions(pp, cfg, bs, pr)
        cfg["_right_aligned_map"] = run.build_right_aligned_citations(pp, cfg, bs, pr)
        vs = run.build_verse_superscript_set(pp, cfg, bs, pr)

        self._log(
            f"  {len(hm)} headings, {len(ho)} ordered, {len(ss)} skips, "
            f"{len(bq)} bq, {len(ci)} cit, {len(vm)} verses, "
            f"{len(ct)} callouts, {len(ib)} bold, {len(vs)} vsup."
        )
        return hm, ho, ss, bq, ci, vm, ct, ib, vs
