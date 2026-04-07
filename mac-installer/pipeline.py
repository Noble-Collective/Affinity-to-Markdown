"""
pipeline.py — Wraps the run.py pipeline for GUI integration.
Captures stdout + stderr (Marker tqdm). Supports OTA updates.
"""

import io, re, sys, threading, traceback, time
from pathlib import Path
from config import MARKER_PDF_DIR, get_template_dir, UPDATES_DIR, get_google_api_key

def _ensure_import_path():
    updated = str(UPDATES_DIR / "marker-pdf")
    bundled = str(MARKER_PDF_DIR)
    for p in [updated, bundled]:
        if p not in sys.path: sys.path.insert(0, p)

class _LogCapture(io.TextIOBase):
    def __init__(self, cb, real): self._cb = cb; self._real = real
    def write(self, t):
        if t and t.strip(): self._cb(t.rstrip("\n"))
        if self._real: self._real.write(t)
        return len(t)
    def flush(self):
        if self._real: self._real.flush()

_TQDM_RE = re.compile(r'(.+?):\s+(\d+)%\|.*?\|\s*(\d+)/(\d+)\s*\[([^<]+)<([^,]+)')

class _TqdmCapture(io.TextIOBase):
    def __init__(self, log_cb, prog_cb, real, base=0.35, end=0.85):
        self._log=log_cb; self._prog=prog_cb; self._real=real
        self._base=base; self._end=end; self._phases=[]; self._buf=""; self._last_pct=-10
    def write(self, text):
        if self._real: self._real.write(text)
        self._buf += text
        while '\r' in self._buf or '\n' in self._buf:
            ir=self._buf.find('\r'); ij=self._buf.find('\n')
            if ir>=0 and (ij<0 or ir<ij): line=self._buf[:ir]; self._buf=self._buf[ir+1:]
            elif ij>=0: line=self._buf[:ij]; self._buf=self._buf[ij+1:]
            else: break
            line=line.strip()
            if line: self._process(line)
        return len(text)
    def _process(self, line):
        m=_TQDM_RE.match(line)
        if not m:
            if line and not line.startswith('\x1b'): self._log(line)
            return
        label,pct,cur,tot=m.group(1).strip(),int(m.group(2)),int(m.group(3)),int(m.group(4))
        elapsed,eta=m.group(5).strip(),m.group(6).strip()
        if label not in self._phases: self._phases.append(label); self._log(f"Marker: {label} ({tot} items)"); self._last_pct=-10
        if pct>=self._last_pct+10: self._log(f"  {label}: {pct}% ({cur}/{tot}) \u2014 elapsed: {elapsed}, ETA: {eta}"); self._last_pct=pct
        est=max(len(self._phases)+1,3); pi=self._phases.index(label); pw=(self._end-self._base)/est
        frac=min(self._base+pi*pw+(pct/100.0)*pw, self._end-0.01)
        self._prog(frac, f"{label}: {pct}% ({cur}/{tot}) \u2014 ETA: {eta}")
    def flush(self):
        if self._real: self._real.flush()

class PipelineRunner:
    def __init__(self, log_callback, progress_callback, done_callback):
        self._log=log_callback; self._progress=progress_callback; self._done=done_callback
        self._thread=None; self._cancelled=False
    @property
    def is_running(self): return self._thread is not None and self._thread.is_alive()
    def cancel(self): self._cancelled=True

    def start_full(self, pdf_path, template, output_path, page_range="", save_raw=False):
        self._cancelled=False
        self._thread=threading.Thread(target=self._run_full, args=(pdf_path,template,output_path,page_range,save_raw), daemon=True)
        self._thread.start()

    def start_postprocess(self, raw_path, pdf_path, template, output_path, page_range=""):
        self._cancelled=False
        self._thread=threading.Thread(target=self._run_postprocess, args=(raw_path,pdf_path,template,output_path,page_range), daemon=True)
        self._thread.start()

    def _run_full(self, pdf_path, template, output_path, page_range_str, save_raw):
        _ensure_import_path()
        old_out,old_err=sys.stdout,sys.stderr
        sys.stdout=_LogCapture(self._log,old_out)
        sys.stderr=_TqdmCapture(self._log,self._progress,old_err,0.35,0.85)
        try:
            import run; pp,op=Path(pdf_path),Path(output_path)
            self._step(0.02,"Loading template config...")
            cfg=self._load_template(run,template); qcfg=self._load_questions(run,template)
            pr=self._parse_page_range(page_range_str)
            if self._check_cancel(): return
            self._step(0.04,"Detecting body font...")
            bfn,bs=run.detect_body_font(pp,pr); self._log(f"Body font: {bfn} @ {bs}pt")
            if self._check_cancel(): return
            self._build_font_maps(run,pp,cfg,bs,pr,0.05,0.15)
            if self._check_cancel(): return
            self._step(0.16,"Importing PyTorch..."); t0=time.time()
            import torch; self._log(f"PyTorch {torch.__version__} loaded ({time.time()-t0:.1f}s)")
            if self._check_cancel(): return
            self._step(0.18,"Patching Marker..."); run.patch_block_relabel()
            self._step(0.20,"Loading ML models (downloads ~500MB on first run)...")
            t0=time.time()
            from marker.models import create_model_dict
            models=create_model_dict(device="cpu",dtype=torch.float32)
            self._log(f"Models loaded: {list(models.keys())} ({time.time()-t0:.1f}s)")
            self._step(0.30,"ML models ready.")
            if self._check_cancel(): return
            self._step(0.32,"Starting Marker PDF extraction...")
            self._log("Marker ML extraction \u2014 per-page progress below...")
            from marker.converters.pdf import PdfConverter
            from config import patch_marker_font_path; patch_marker_font_path()
            mcfg={"lowres_image_dpi":96,"block_relabel_str":"SectionHeader:Text:0.6,Figure:Text:1.0,Picture:Text:1.0",
                "level_count":4,"default_level":3,"common_element_threshold":0.15,"text_match_threshold":85,
                "BlockquoteProcessor_min_x_indent":0.01,"BlockquoteProcessor_x_start_tolerance":0.05,
                "BlockquoteProcessor_x_end_tolerance":0.05,"TextProcessor_column_gap_ratio":0.06,
                "disable_links":True,"disable_ocr":True,"pdftext_workers":1,
                "disable_image_extraction":True,"extract_images":False}
            gak=get_google_api_key(); llm=None
            if gak:
                mn=run.get_available_gemini_model(gak); mcfg["gemini_api_key"]=gak; mcfg["gemini_model_name"]=mn
                llm="marker.services.gemini.GoogleGeminiService"; self._log(f"LLM enabled: {mn}")
            else: self._log("LLM disabled: no API key")
            if pr: mcfg["page_range"]=pr
            self._step(0.35,"Running Marker..."); t0=time.time()
            conv=PdfConverter(artifact_dict=models,processor_list=None,config=mcfg,llm_service=llm)
            rendered=conv(str(pp)); self._log(f"Marker complete ({time.time()-t0:.0f}s)")
            if save_raw:
                rp=op.with_suffix(".raw.md"); rp.write_text(rendered.markdown,encoding="utf-8"); self._log(f"Raw saved: {rp}")
            if self._check_cancel(): return
            self._step(0.88,"Running post-processing (30+ passes)..."); t0=time.time()
            md=run.post_process(rendered.markdown,*self._font_maps,cfg,*self._extra_maps,questions_cfg=qcfg)
            self._log(f"Post-processing complete ({time.time()-t0:.1f}s)")
            op.write_text(md,encoding="utf-8"); self._step(1.0,"Done!")
            self._log(f"Output: {op} ({len(md.splitlines())} lines)"); self._done(True,str(op),None)
        except Exception as e:
            self._log(f"ERROR: {e}"); self._log(traceback.format_exc()); self._done(False,None,str(e))
        finally: sys.stdout=old_out; sys.stderr=old_err

    def _run_postprocess(self, raw_path, pdf_path, template, output_path, page_range_str):
        _ensure_import_path()
        old_out=sys.stdout; sys.stdout=_LogCapture(self._log,old_out)
        try:
            import run; rp,pp,op=Path(raw_path),Path(pdf_path),Path(output_path)
            self._step(0.03,"Loading template config...")
            cfg=self._load_template(run,template); qcfg=self._load_questions(run,template)
            pr=self._parse_page_range(page_range_str)
            if self._check_cancel(): return
            self._step(0.08,"Detecting body font...")
            bfn,bs=run.detect_body_font(pp,pr); self._log(f"Body font: {bfn} @ {bs}pt")
            if self._check_cancel(): return
            self._build_font_maps(run,pp,cfg,bs,pr,0.12,0.45)
            if self._check_cancel(): return
            self._step(0.50,"Running post-processing (30+ passes)..."); t0=time.time()
            raw=rp.read_text(encoding="utf-8")
            md=run.post_process(raw,*self._font_maps,cfg,*self._extra_maps,questions_cfg=qcfg)
            self._log(f"Post-processing complete ({time.time()-t0:.1f}s)")
            op.write_text(md,encoding="utf-8"); self._step(1.0,"Done!")
            self._log(f"Output: {op} ({len(md.splitlines())} lines)"); self._done(True,str(op),None)
        except Exception as e:
            self._log(f"ERROR: {e}"); self._log(traceback.format_exc()); self._done(False,None,str(e))
        finally: sys.stdout=old_out

    def _step(self,f,l): self._progress(f,l); self._log(l)
    def _check_cancel(self):
        if self._cancelled: self._done(False,None,"Cancelled"); return True
        return False
    def _parse_page_range(self,s):
        s=s.strip()
        if not s: return None
        pages=[]
        for p in s.split(","):
            p=p.strip()
            if "-" in p: a,b=p.split("-",1); pages.extend(range(int(a),int(b)+1))
            else: pages.append(int(p))
        return pages
    def _load_template(self,run,template):
        td=get_template_dir(template); cp=td/"pdf_config.yaml"
        if not cp.exists(): raise FileNotFoundError(f"Template not found: {cp}")
        cfg=run._load_yaml(cp); cfg["_citation_res"]=[re.compile(p) for p in cfg.get("citation_patterns",[])]
        self._log(f"Template: {template} (from {td})"); return cfg
    def _load_questions(self,run,template):
        td=get_template_dir(template); qp=td/"questions_final.yaml"
        if qp.exists():
            qd=run._load_yaml(qp); qc=qd.get("questions",[]); self._log(f"Questions config: {len(qc)} entries"); return qc
        return None
    def _build_font_maps(self,run,pp,cfg,bs,pr,base,end):
        total=9; s=(end-base)/total
        def ms(i,n): self._step(base+i*s,f"Building font maps ({i+1}/{total}: {n})...")
        ms(0,"headings"); hm,ho=run.build_heading_map(pp,cfg,bs,pr); self._log(f"  {len(hm)} headings, {len(ho)} ordered")
        ms(1,"skip set"); ss=run.build_skip_set(pp,cfg,bs,pr); self._log(f"  {len(ss)} skips")
        ms(2,"blockquotes"); bq,ci=run.build_blockquote_set(pp,cfg,bs,pr); self._log(f"  {len(bq)} bq, {len(ci)} cit")
        ms(3,"verses"); vm=run.build_verse_map(pp,cfg,bs,pr); self._log(f"  {len(vm)} verses")
        ms(4,"callouts"); ct=run.build_callout_set(pp,cfg,bs,pr); self._log(f"  {len(ct)} callouts")
        ms(5,"inline bold"); ib=run.build_inline_bold_set(pp,cfg,bs,pr); self._log(f"  {len(ib)} bold")
        ms(6,"rotated subdivisions"); cfg["_rotated_subdivisions"]=run.build_rotated_subdivisions(pp,cfg,bs,pr)
        ms(7,"right-aligned citations"); cfg["_right_aligned_map"]=run.build_right_aligned_citations(pp,cfg,bs,pr)
        ms(8,"verse superscripts"); vs=run.build_verse_superscript_set(pp,cfg,bs,pr); self._log(f"  {len(vs)} vsup")
        self._step(end,"Font maps complete.")
        self._font_maps=(hm,ss,bq,ci,vm); self._extra_maps=(ct,ib,ho,vs)
