"""
calibrate.py — Extracts font data, Marker output, and PyMuPDF spans
for new book template calibration. Produces 3 files that get uploaded
to Claude to build a pdf_config.yaml.
"""

import io, json, os, re, sys, threading, traceback, time
from pathlib import Path


def _ensure_import_path():
    from config import UPDATES_DIR, MARKER_PDF_DIR
    for p in [str(UPDATES_DIR / "marker-pdf"), str(MARKER_PDF_DIR)]:
        if p not in sys.path:
            sys.path.insert(0, p)


class CalibrateRunner:
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

    def start(self, pdf_path, book_name):
        self._cancelled = False
        self._thread = threading.Thread(
            target=self._run, args=(pdf_path, book_name), daemon=True)
        self._thread.start()

    def _step(self, frac, label):
        self._progress(frac, label)
        self._log(label)

    def _check_cancel(self):
        if self._cancelled:
            self._done(False, None, "Cancelled")
            return True
        return False

    def _run(self, pdf_path, book_name):
        try:
            pp = Path(pdf_path)
            out_dir = pp.parent / f"{pp.stem}_calibration"
            out_dir.mkdir(exist_ok=True)

            self._step(0.01, "Step 1/3: Font analysis \u2014 scanning all pages...")
            self._extract_font_summary(pp, out_dir, book_name)
            if self._check_cancel(): return

            self._step(0.10, "Step 2/3: Marker extraction \u2014 loading models...")
            self._run_marker(pp, out_dir, book_name)
            if self._check_cancel(): return

            self._step(0.85, "Step 3/3: PyMuPDF span extraction...")
            self._extract_span_data(pp, out_dir, book_name)
            if self._check_cancel(): return

            self._step(1.0, "Calibration complete!")
            self._log(f"Output folder: {out_dir}")
            self._log(f"  {book_name}_font_summary.txt \u2014 font signatures with stats and samples")
            self._log(f"  {book_name}_raw.md \u2014 Marker's unprocessed output")
            self._log(f"  {book_name}_pdf_data.json \u2014 every text span with font, size, position")
            self._log("")
            self._log("Upload all 3 files to Claude to build a pdf_config.yaml template.")
            self._done(True, str(out_dir), None)
        except Exception as e:
            self._log(f"ERROR: {e}")
            self._log(traceback.format_exc())
            self._done(False, None, str(e))

    def _extract_font_summary(self, pdf_path, out_dir, book_name):
        import fitz
        doc = fitz.open(str(pdf_path))
        total_pages = len(doc)
        self._log(f"  Scanning {total_pages} pages...")
        font_data = {}

        for pn in range(total_pages):
            if self._cancelled: doc.close(); return
            if pn > 0 and pn % 50 == 0:
                self._log(f"  Page {pn}/{total_pages}...")
                self._progress(0.01 + 0.08 * pn / total_pages,
                               f"Font analysis: page {pn}/{total_pages}")
            page = doc[pn]
            for block in page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]:
                if "lines" not in block: continue
                for line in block["lines"]:
                    for span in line["spans"]:
                        text = span["text"].strip()
                        if not text: continue
                        font = span["font"]
                        size = round(span["size"], 1)
                        flags = span["flags"]
                        is_b = bool(flags & (1 << 4))
                        is_i = bool(flags & (1 << 1))
                        key = (font, size, is_b, is_i)
                        if key not in font_data:
                            font_data[key] = dict(font=font, size=size, bold=is_b,
                                italic=is_i, count=0, pages=set(), x_pos=[], lengths=[], samples=[])
                        e = font_data[key]
                        e["count"] += 1
                        e["pages"].add(pn + 1)
                        e["x_pos"].append(round(span["bbox"][0]))
                        e["lengths"].append(len(text))
                        if len(e["samples"]) < 4 and len(text) > 10:
                            e["samples"].append((pn + 1, text[:100]))
        doc.close()

        body_key = max(font_data, key=lambda k: font_data[k]["count"])
        body_size = font_data[body_key]["size"]
        body_font = font_data[body_key]["font"]
        sorted_sigs = sorted(font_data.values(), key=lambda e: -e["count"])

        def guess_role(e):
            ratio = e["size"] / body_size if body_size else 1
            avg_len = sum(e["lengths"]) / max(len(e["lengths"]), 1)
            avg_x = sum(e["x_pos"]) / max(len(e["x_pos"]), 1)
            page_pct = len(e["pages"]) / total_pages * 100
            if e is font_data[body_key]:
                return "BODY (most frequent)"
            if e["bold"] and ratio > 1.4 and avg_len < 50:
                return f"HEADING (bold, {ratio:.1f}x body, short lines)"
            if e["bold"] and 0.95 <= ratio <= 1.05:
                return "INLINE BOLD (body-sized, bold)"
            if e["italic"] and 0.95 <= ratio <= 1.05:
                return "INLINE ITALIC (body-sized, italic)"
            if ratio < 0.85 and avg_x > 300:
                return "CITATION (small, right-aligned)"
            if ratio < 0.85:
                return "SMALL TEXT (superscript/footer?)"
            if ratio > 1.2 and not e["bold"] and avg_len > 40:
                return "CALLOUT/PULL QUOTE (larger, not bold)"
            if page_pct > 80 and avg_len < 20:
                return "RUNNING HEADER/FOOTER (most pages, short)"
            if ratio > 1.1 and avg_len < 40:
                return f"SUB-HEADING ({ratio:.1f}x body, short lines)"
            return "UNKNOWN \u2014 review samples"

        lines = []
        lines.append(f"FONT ANALYSIS \u2014 {pdf_path.name}")
        lines.append("=" * 60)
        lines.append(f"Body font: {body_font} @ {body_size}pt")
        lines.append(f"Total pages: {total_pages}")
        lines.append(f"Unique font signatures: {len(font_data)}")
        lines.append("")

        for i, e in enumerate(sorted_sigs):
            ratio = e["size"] / body_size if body_size else 1
            avg_x = sum(e["x_pos"]) / max(len(e["x_pos"]), 1)
            min_x = min(e["x_pos"]) if e["x_pos"] else 0
            max_x = max(e["x_pos"]) if e["x_pos"] else 0
            avg_len = sum(e["lengths"]) / max(len(e["lengths"]), 1)
            pc = len(e["pages"])
            fp = min(e["pages"]) if e["pages"] else 0
            lp = max(e["pages"]) if e["pages"] else 0
            fl = ("bold " if e["bold"] else "") + ("italic " if e["italic"] else "")
            if not fl: fl = "regular"

            lines.append(f"[SIG-{i+1:02d}] {e['font']} {e['size']}pt (ratio: {ratio:.2f}x)")
            lines.append(f"  Flags: {fl.strip()}")
            lines.append(f"  Occurrences: {e['count']} spans across {pc}/{total_pages} pages (pp. {fp}\u2013{lp})")
            lines.append(f"  Position: avg_x={avg_x:.0f}, range_x=[{min_x}, {max_x}], avg_line_len={avg_len:.0f} chars")
            lines.append(f"  Likely role: {guess_role(e)}")
            lines.append(f"  Samples:")
            for pg, txt in e["samples"]:
                lines.append(f'    p.{pg}: "{txt}"')
            lines.append("")

        out_path = out_dir / f"{book_name}_font_summary.txt"
        out_path.write_text("\n".join(lines), encoding="utf-8")
        self._log(f"  Saved: {out_path.name} ({len(font_data)} signatures)")

    def _run_marker(self, pdf_path, out_dir, book_name):
        _ensure_import_path()
        old_out, old_err = sys.stdout, sys.stderr
        _TQDM_RE = re.compile(r'(.+?):\s+(\d+)%\|.*?\|\s*(\d+)/(\d+)\s*\[([^<]+)<([^,]+)')

        class _LogCap(io.TextIOBase):
            def __init__(s, cb, real): s._cb=cb; s._real=real
            def write(s, t):
                if t and t.strip(): s._cb(t.rstrip("\n"))
                if s._real: s._real.write(t)
                return len(t)
            def flush(s):
                if s._real: s._real.flush()

        class _TqdmCap(io.TextIOBase):
            def __init__(s, log, prog, real):
                s._log=log; s._prog=prog; s._real=real
                s._buf=""; s._phases=[]; s._last=-10
            def write(s, text):
                if s._real: s._real.write(text)
                s._buf += text
                while '\r' in s._buf or '\n' in s._buf:
                    ir=s._buf.find('\r'); ij=s._buf.find('\n')
                    if ir>=0 and (ij<0 or ir<ij): ln=s._buf[:ir]; s._buf=s._buf[ir+1:]
                    elif ij>=0: ln=s._buf[:ij]; s._buf=s._buf[ij+1:]
                    else: break
                    ln=ln.strip()
                    if ln: s._proc(ln)
                return len(text)
            def _proc(s, ln):
                m=_TQDM_RE.match(ln)
                if not m:
                    if ln and not ln.startswith('\x1b'): s._log(ln)
                    return
                label,pct,cur,tot = m.group(1).strip(),int(m.group(2)),int(m.group(3)),int(m.group(4))
                el,eta = m.group(5).strip(),m.group(6).strip()
                if label not in s._phases:
                    s._phases.append(label); s._log(f"Marker: {label} ({tot} items)"); s._last=-10
                if pct >= s._last+10:
                    s._log(f"  {label}: {pct}% ({cur}/{tot}) \u2014 elapsed: {el}, ETA: {eta}"); s._last=pct
                frac = 0.10 + (pct/100.0)*0.73
                s._prog(min(frac, 0.84), f"Marker: {label} {pct}% ({cur}/{tot}) \u2014 ETA: {eta}")
            def flush(s):
                if s._real: s._real.flush()

        sys.stdout = _LogCap(self._log, old_out)
        sys.stderr = _TqdmCap(self._log, self._progress, old_err)
        try:
            self._log("  Importing PyTorch...")
            t0 = time.time()
            import torch
            self._log(f"  PyTorch {torch.__version__} ({time.time()-t0:.1f}s)")
            if self._cancelled: return

            self._log("  Loading ML models (downloads ~500MB first time)...")
            t0 = time.time()
            from marker.models import create_model_dict
            models = create_model_dict(device="cpu", dtype=torch.float32)
            self._log(f"  Models loaded ({time.time()-t0:.1f}s)")
            if self._cancelled: return

            try:
                import run; run.patch_block_relabel()
            except Exception: pass

            self._log("  Starting Marker on full PDF...")
            from marker.converters.pdf import PdfConverter
            from config import patch_marker_font_path; patch_marker_font_path()
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
            t0 = time.time()
            conv = PdfConverter(artifact_dict=models, processor_list=None, config=mcfg, llm_service=None)
            rendered = conv(str(pdf_path))
            self._log(f"  Marker complete ({time.time()-t0:.0f}s)")

            out_path = out_dir / f"{book_name}_raw.md"
            out_path.write_text(rendered.markdown, encoding="utf-8")
            self._log(f"  Saved: {out_path.name} ({len(rendered.markdown.splitlines())} lines)")
        finally:
            sys.stdout = old_out
            sys.stderr = old_err

    def _extract_span_data(self, pdf_path, out_dir, book_name):
        import fitz
        doc = fitz.open(str(pdf_path))
        total = len(doc)
        self._log(f"  Extracting spans from {total} pages...")
        pages = []

        for pn in range(total):
            if self._cancelled: doc.close(); return
            if pn > 0 and pn % 50 == 0:
                self._log(f"  Page {pn}/{total}...")
                self._progress(0.85 + 0.14 * pn / total, f"PyMuPDF: page {pn}/{total}")

            page = doc[pn]
            pd = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
            pdata = {"p": pn+1, "w": round(pd["width"]), "h": round(pd["height"]), "blocks": []}

            for block in pd["blocks"]:
                if "lines" not in block: continue
                bd = {"b": [round(x) for x in block["bbox"]], "lines": []}
                for line in block["lines"]:
                    ld = {"b": [round(x) for x in line["bbox"]], "spans": []}
                    for span in line["spans"]:
                        t = span["text"]
                        if not t.strip(): continue
                        fl = span["flags"]
                        fs = ("B" if fl & (1<<4) else "") + ("I" if fl & (1<<1) else "")
                        if not fs: fs = "R"
                        ld["spans"].append({"f": span["font"], "s": round(span["size"],1),
                            "fl": fs, "b": [round(x) for x in span["bbox"]], "t": t})
                    if ld["spans"]: bd["lines"].append(ld)
                if bd["lines"]: pdata["blocks"].append(bd)
            pages.append(pdata)

        doc.close()
        out_path = out_dir / f"{book_name}_pdf_data.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({"pages": pages}, f, ensure_ascii=False)
        mb = out_path.stat().st_size / (1024*1024)
        self._log(f"  Saved: {out_path.name} ({mb:.1f} MB, {total} pages)")
