"""
pipeline.py — Wraps the run.py pipeline for GUI integration.

Runs the conversion in a background thread, reporting progress and log
messages back to the GUI via callbacks.  Captures both stdout (run.py
print statements) and stderr (Marker's tqdm progress bars) to provide
real-time progress updates in the GUI.
"""

import io
import re
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
    """Captures stdout and forwards to a callback."""
    def __init__(self, callback, real_stream):
        self._callback = callback
        self._real = real_stream

    def write(self, text):
        if text and text.strip():
            self._callback(text.rstrip("\n"))
        if self._real:
            self._real.write(text)
        return len(text)

    def flush(self):
        if self._real:
            self._real.flush()


# Regex to parse tqdm output like:
#   Recognizing Layout:  22%|█████| 108/481 [18:39<1:03:26, 10.20s/it]
_TQDM_RE = re.compile(
    r'(.+?):\s+(\d+)%\|.*?\|\s*(\d+)/(\d+)\s*\[([^<]+)<([^,]+)'
)


class _TqdmCapture(io.TextIOBase):
    """
    Captures stderr, parses tqdm progress bars from Marker, and
    forwards progress updates to GUI callbacks.

    tqdm uses \\r (carriage return) to overwrite lines, so we buffer
    text and process on each \\r or \\n.
    """
    def __init__(self, log_callback, progress_callback, real_stderr,
                 progress_base=0.35, progress_end=0.85):
        self._log = log_callback
        self._progress = progress_callback
        self._real = real_stderr
        self._base = progress_base
        self._end = progress_end
        self._phases_seen = []
        self._buffer = ""
        self._last_log_pct = -10  # only log every 10%

    def write(self, text):
        if self._real:
            self._real.write(text)

        self._buffer += text

        # Process complete lines (tqdm uses \r to overwrite)
        while '\r' in self._buffer or '\n' in self._buffer:
            idx_r = self._buffer.find('\r')
            idx_n = self._buffer.find('\n')
            if idx_r >= 0 and (idx_n < 0 or idx_r < idx_n):
                line = self._buffer[:idx_r]
                self._buffer = self._buffer[idx_r + 1:]
            elif idx_n >= 0:
                line = self._buffer[:idx_n]
                self._buffer = self._buffer[idx_n + 1:]
            else:
                break
            line = line.strip()
            if line:
                self._process_line(line)

        return len(text)

    def _process_line(self, line):
        m = _TQDM_RE.match(line)
        if not m:
            # Non-tqdm stderr line — log it (skip ANSI escape sequences)
            if line and not line.startswith('\x1b'):
                self._log(line)
            return

        label = m.group(1).strip()
        pct = int(m.group(2))
        current = int(m.group(3))
        total = int(m.group(4))
        elapsed = m.group(5).strip()
        eta = m.group(6).strip()

        # Track phase transitions
        if label not in self._phases_seen:
            self._phases_seen.append(label)
            self._log(f"Marker: {label} ({total} items)")
            self._last_log_pct = -10

        # Log progress every 10% within each phase
        if pct >= self._last_log_pct + 10:
            self._log(f"  {label}: {pct}% ({current}/{total}) — elapsed: {elapsed}, ETA: {eta}")
            self._last_log_pct = pct

        # Map to overall progress bar.
        # Divide the Marker range among phases seen so far.
        n_phases = max(len(self._phases_seen), 1)
        est_total = max(n_phases + 1, 3)  # assume at least 3 phases
        phase_idx = self._phases_seen.index(label)
        phase_width = (self._end - self._base) / est_total
        phase_base = self._base + phase_idx * phase_width
        frac = phase_base + (pct / 100.0) * phase_width
        frac = min(frac, self._end - 0.01)

        self._progress(frac, f"{label}: {pct}% ({current}/{total}) — ETA: {eta}")

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
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout = _LogCapture(self._log, old_stdout)
        sys.stderr = _TqdmCapture(self._log, self._progress, old_stderr, 0.35, 0.85)
        try:
            import run
            pp, op = Path(pdf_path), Path(output_path)

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
            self._log("Marker ML extraction — per-page progress will appear below...")
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

            self._step(0.35, "Running Marker...")
            t0 = time.time()
            conv = PdfConverter(artifact_dict=models, processor_list=None, config=mcfg, llm_service=llm)
            rendered = conv(str(pp))
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
            sys.stderr = old_stderr

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
