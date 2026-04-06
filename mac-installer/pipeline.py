"""
pipeline.py — Wraps the run.py pipeline for GUI integration.

Runs the conversion in a background thread, reporting progress and log
messages back to the GUI via callbacks.  The GUI polls a queue to pick
up these messages without blocking the tkinter event loop.
"""

import io
import sys
import threading
import traceback
import time
from pathlib import Path
from typing import Callable, Optional

from config import MARKER_PDF_DIR


def _ensure_import_path():
    mp = str(MARKER_PDF_DIR)
    if mp not in sys.path:
        sys.path.insert(0, mp)


class _LogCapture(io.TextIOBase):
    def __init__(self, callback, real_stdout):
        self._callback = callback
        self._real = real_stdout

    def write(self, text):
        if text and text.strip():
            self._callback(text.rstrip("\n"))
        if self._real:
            self._real.write(text)
        return len(text)

    def flush(self):
        if self._real:
            self._real.flush()


class PipelineRunner:
    def __init__(self, log_callback, progress_callback, done_callback):
        self._log = log_callback
        self._progress = progress_callback
        self._done = done_callback
        self._thread = None
        self._cancelled = False

    @property
    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def cancel(self):
        self._cancelled = True

    def start_full(self, pdf_path, template, output_path, page_range="", save_raw=False):
        self._cancelled = False
        self._thread = threading.Thread(
            target=self._run_full,
            args=(pdf_path, template, output_path, page_range, save_raw),
            daemon=True,
        )
        self._thread.start()

    def start_postprocess(self, raw_path, pdf_path, template, output_path, page_range=""):
        self._cancelled = False
        self._thread = threading.Thread(
            target=self._run_postprocess,
            args=(raw_path, pdf_path, template, output_path, page_range),
            daemon=True,
        )
        self._thread.start()

    # ── Full conversion ────────────────────────────────────────────────────

    def _run_full(self, pdf_path, template, output_path, page_range_str, save_raw):
        _ensure_import_path()
        old_stdout = sys.stdout
        sys.stdout = _LogCapture(self._log, old_stdout)
        try:
            import run
            pp = Path(pdf_path)
            op = Path(output_path)

            self._step(0.02, "Loading template config...")
            cfg = run.load_template(template)
            self._log(f"Template: {template}")
            qcfg = self._load_questions(template, run)
            pr = self._parse_page_range(page_range_str)
            if self._check_cancel(): return

            self._step(0.04, "Detecting body font...")
            bfn, bs = run.detect_body_font(pp, pr)
            self._log(f"Body font: {bfn} @ {bs}pt")
            if self._check_cancel(): return

            self._build_font_maps_with_progress(run, pp, cfg, bs, pr, 0.05, 0.15)
            if self._check_cancel(): return

            self._step(0.16, "Importing PyTorch (may take a moment)...")
            t0 = time.time()
            import torch
            self._log(f"PyTorch {torch.__version__} loaded ({time.time()-t0:.1f}s)")
            if self._check_cancel(): return

            self._step(0.18, "Patching Marker block relabel...")
            run.patch_block_relabel()

            self._step(0.20, "Loading ML models (downloads ~500MB on first run)...")
            self._log("Loading surya models — may take a few minutes on first run...")
            t0 = time.time()
            from marker.models import create_model_dict
            models = create_model_dict(device="cpu", dtype=torch.float32)
            self._log(f"Models loaded: {list(models.keys())} ({time.time()-t0:.1f}s)")
            self._step(0.30, "ML models ready.")
            if self._check_cancel(): return

            self._step(0.32, "Starting Marker PDF extraction...")
            self._log("Marker ML extraction — the slow step (~10-15 min on CPU)...")
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

            self._step(0.35, "Running Marker (this takes a while)...")
            t0 = time.time()
            ticker_stop = threading.Event()
            ticker = threading.Thread(
                target=self._progress_ticker,
                args=(ticker_stop, 0.35, 0.85, "Marker extracting"),
                daemon=True,
            )
            ticker.start()
            conv = PdfConverter(artifact_dict=models, processor_list=None, config=mcfg, llm_service=llm)
            rendered = conv(str(pp))
            ticker_stop.set()
            ticker.join(timeout=2)
            self._log(f"Marker extraction complete ({time.time()-t0:.0f}s)")

            if save_raw:
                rp = op.with_suffix(".raw.md")
                rp.write_text(rendered.markdown, encoding="utf-8")
                self._log(f"Raw saved: {rp}")
            if self._check_cancel(): return

            self._step(0.88, "Running post-processing (30+ passes)...")
            t0 = time.time()
            md = run.post_process(rendered.markdown, *self._font_maps, cfg, *self._extra_maps, questions_cfg=qcfg)
            self._log(f"Post-processing complete ({time.time()-t0:.1f}s)")

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

    # ── Post-process only ──────────────────────────────────────────────────

    def _run_postprocess(self, raw_path, pdf_path, template, output_path, page_range_str):
        _ensure_import_path()
        old_stdout = sys.stdout
        sys.stdout = _LogCapture(self._log, old_stdout)
        try:
            import run
            rp, pp, op = Path(raw_path), Path(pdf_path), Path(output_path)

            self._step(0.03, "Loading template config...")
            cfg = run.load_template(template)
            self._log(f"Template: {template}")
            qcfg = self._load_questions(template, run)
            pr = self._parse_page_range(page_range_str)
            if self._check_cancel(): return

            self._step(0.08, "Detecting body font...")
            bfn, bs = run.detect_body_font(pp, pr)
            self._log(f"Body font: {bfn} @ {bs}pt")
            if self._check_cancel(): return

            self._build_font_maps_with_progress(run, pp, cfg, bs, pr, 0.12, 0.45)
            if self._check_cancel(): return

            self._step(0.50, "Running post-processing (30+ passes)...")
            t0 = time.time()
            raw = rp.read_text(encoding="utf-8")
            md = run.post_process(raw, *self._font_maps, cfg, *self._extra_maps, questions_cfg=qcfg)
            self._log(f"Post-processing complete ({time.time()-t0:.1f}s)")

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

    # ── Helpers ───────────────────────────────────────────────────────────

    def _step(self, fraction, label):
        self._progress(fraction, label)
        self._log(label)

    def _check_cancel(self):
        if self._cancelled:
            self._done(False, None, "Cancelled")
            return True
        return False

    def _parse_page_range(self, s):
        s = s.strip()
        if not s: return None
        pages = []
        for part in s.split(","):
            part = part.strip()
            if "-" in part:
                a, b = part.split("-", 1)
                pages.extend(range(int(a), int(b) + 1))
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

    def _build_font_maps_with_progress(self, run, pp, cfg, bs, pr, base_frac, end_frac):
        total = 9
        step = (end_frac - base_frac) / total

        def ms(i, name):
            self._step(base_frac + i * step, f"Building font maps ({i+1}/{total}: {name})...")

        ms(0, "headings")
        hm, ho = run.build_heading_map(pp, cfg, bs, pr)
        self._log(f"  {len(hm)} headings, {len(ho)} in document order")

        ms(1, "skip set")
        ss = run.build_skip_set(pp, cfg, bs, pr)
        self._log(f"  {len(ss)} skip entries")

        ms(2, "blockquotes & citations")
        bq, ci = run.build_blockquote_set(pp, cfg, bs, pr)
        self._log(f"  {len(bq)} blockquotes, {len(ci)} citations")

        ms(3, "verse text")
        vm = run.build_verse_map(pp, cfg, bs, pr)
        self._log(f"  {len(vm)} verse entries")

        ms(4, "callouts")
        ct = run.build_callout_set(pp, cfg, bs, pr)
        self._log(f"  {len(ct)} callout texts")

        ms(5, "inline bold")
        ib = run.build_inline_bold_set(pp, cfg, bs, pr)
        self._log(f"  {len(ib)} bold phrases")

        ms(6, "rotated subdivisions")
        cfg["_rotated_subdivisions"] = run.build_rotated_subdivisions(pp, cfg, bs, pr)

        ms(7, "right-aligned citations")
        cfg["_right_aligned_map"] = run.build_right_aligned_citations(pp, cfg, bs, pr)

        ms(8, "verse superscripts")
        vs = run.build_verse_superscript_set(pp, cfg, bs, pr)
        self._log(f"  {len(vs)} verse superscripts")

        self._step(end_frac, "Font maps complete.")
        self._font_maps = (hm, ss, bq, ci, vm)
        self._extra_maps = (ct, ib, ho, vs)

    def _progress_ticker(self, stop_event, start_frac, end_frac, label):
        """Slowly advances progress bar while Marker runs, so the app
        never appears frozen. Uses a log curve that never reaches end_frac."""
        elapsed = 0
        while not stop_event.is_set():
            stop_event.wait(timeout=3.0)
            if stop_event.is_set(): break
            elapsed += 3
            progress = 1.0 - (1.0 / (1.0 + elapsed / 60.0))
            frac = start_frac + progress * (end_frac - start_frac)
            m, s = divmod(elapsed, 60)
            ts = f"{m}m {s}s" if m > 0 else f"{s}s"
            self._progress(frac, f"{label}... ({ts} elapsed)")
