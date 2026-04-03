#!/usr/bin/env python
"""
run.py - Local runner for PDF to Markdown conversion.

All book-specific configuration lives in templates/<template>/pdf_config.yaml.
The conversion logic is fully generic -- font ratios and weight patterns are
used instead of hardcoded font names or absolute sizes.

Usage:
  python run.py path/to/book.pdf                    # full conversion
  python run.py path/to/book.pdf --save-raw         # save Marker output before post-processing
  python run.py raw.md book.pdf --postprocess       # re-run post-processing only (fast)
  python run.py path/to/book.pdf --template homestead
  python run.py path/to/book.pdf --page-range 62-200
  python run.py path/to/book.pdf --dump-fonts       # calibration mode
  python run.py path/to/book.pdf --verbose           # show Marker/LLM logging
"""
import os, sys, re, argparse, logging
from pathlib import Path

logging.basicConfig(level=logging.WARNING, format="%(name)s: %(message)s")
SCRIPT_DIR = Path(__file__).resolve().parent

def _load_yaml(path):
    import yaml
    with open(path, encoding="utf-8") as f: return yaml.safe_load(f)

def load_template(name):
    path = SCRIPT_DIR / "templates" / name / "pdf_config.yaml"
    if not path.exists(): print(f"ERROR: {path}"); sys.exit(1)
    cfg = _load_yaml(path)
    cfg["_citation_res"] = [re.compile(p) for p in cfg.get("citation_patterns", [])]
    return cfg

def size_bucket(s): return round(float(s) * 2) / 2

def font_weight(f):
    n = f.lower()
    if "bolditalic" in n or ("bold" in n and "italic" in n): return "bold-italic"
    if "bold" in n: return "bold"
    if "italic" in n: return "italic"
    return "regular"

def normalise_key(text):
    t = re.sub(r"\*+", "", text)
    t = t.replace("\u2018","'").replace("\u2019","'").replace("\u201c",'"').replace("\u201d",'"')
    t = t.replace("\u2013","-").replace("\u2014","-")
    return " ".join(t.split()).strip().lower()[:60]

def _match_rule(w, r, rule):
    return rule["weight"] == w and rule["min_ratio"] <= r <= rule["max_ratio"]

# ---- PDF font scanning ----

def detect_body_font(pdf_path, page_range=None):
    import fitz
    doc = fitz.open(str(pdf_path))
    pages = range(doc.page_count) if page_range is None else [p for p in page_range if p < doc.page_count]
    freq = {}
    for pi in pages:
        for block in doc[pi].get_text("dict")["blocks"]:
            if block.get("type") != 0: continue
            for line in block.get("lines",[]):
                for span in line.get("spans",[]):
                    t = span["text"].strip()
                    if any(c.isalpha() for c in t):
                        k = (span["font"], size_bucket(span["size"]))
                        freq[k] = freq.get(k,0) + len(t)
    return max(freq, key=freq.get) if freq else ("unknown", 10.0)

def build_heading_map(pdf_path, cfg, body_size, page_range=None):
    import fitz
    hmap = {}; horder = []
    doc = fitz.open(str(pdf_path))
    pages = range(doc.page_count) if page_range is None else [p for p in page_range if p < doc.page_count]
    rules = cfg.get("headings",[]); skip_ratio = cfg.get("skip_large_ratio", 2.4)
    for pi in pages:
        for block in doc[pi].get_text("dict", sort=True)["blocks"]:
            if block.get("type") != 0: continue
            fc = {}
            for line in block.get("lines",[]):
                for span in line.get("spans",[]):
                    t = span["text"].strip()
                    if any(c.isalpha() for c in t):
                        k = (span["font"], size_bucket(span["size"]))
                        fc[k] = fc.get(k,0) + len(t)
            if not fc: continue
            df, ds = max(fc, key=fc.get); ratio = ds / body_size; w = font_weight(df)
            if ratio > skip_ratio: continue
            level = None
            for rule in rules:
                if _match_rule(w, ratio, rule): level = rule["level"]; break
            if level is None: continue
            parts = []
            for line in block.get("lines",[]):
                for span in line.get("spans",[]):
                    sk = (span["font"], size_bucket(span["size"]))
                    if sk == (df, ds) and span["text"].strip(): parts.append(span["text"].strip())
            text = " ".join(" ".join(parts).split()).strip()
            if text and len(text) > 2:
                key = normalise_key(text); lvl = "#" * level
                if key not in hmap: hmap[key] = []
                hmap[key].append(lvl); horder.append((text, lvl))
    return hmap, horder

def build_skip_set(pdf_path, cfg, body_size, page_range=None):
    import fitz
    skip = set(); doc = fitz.open(str(pdf_path))
    pages = range(doc.page_count) if page_range is None else [p for p in page_range if p < doc.page_count]
    rh_sig = cfg.get("running_header_signature",[]); skip_ratio = cfg.get("skip_large_ratio", 2.4)
    for pi in pages:
        for block in doc[pi].get_text("dict", sort=True)["blocks"]:
            if block.get("type") != 0: continue
            wr = set(); text = ""
            for line in block.get("lines",[]):
                for span in line.get("spans",[]):
                    t = span["text"].strip()
                    if t: r = size_bucket(span["size"]) / body_size; wr.add((font_weight(span["font"]), r)); text += span["text"]
            text = " ".join(text.split()).strip()
            if not text: continue
            if re.match(r"^\d{1,3}$", text): skip.add(normalise_key(text)); continue
            if any(r > skip_ratio for _,r in wr): skip.add(normalise_key(text)); continue
            if rh_sig and all(any(_match_rule(w,r,rule) for w,r in wr) for rule in rh_sig): skip.add(normalise_key(text))
    return skip

def build_blockquote_set(pdf_path, cfg, body_size, page_range=None):
    import fitz
    bq, cit = set(), set(); doc = fitz.open(str(pdf_path))
    pages = range(doc.page_count) if page_range is None else [p for p in page_range if p < doc.page_count]
    mr = cfg.get("quote_max_ratio", 0.88); cm = cfg.get("citation_max_chars", 80)
    for pi in pages:
        for block in doc[pi].get_text("dict", sort=True)["blocks"]:
            if block.get("type") != 0: continue
            fc = {}; text = ""
            for line in block.get("lines",[]):
                for span in line.get("spans",[]):
                    t = span["text"]
                    if t.strip(): k = (span["font"], size_bucket(span["size"])); fc[k] = fc.get(k,0) + len(t.strip())
                    text += t
            if not fc: continue
            _, ds = max(fc, key=fc.get)
            if ds / body_size > mr: continue
            text = " ".join(text.split()).strip()
            if not text or not any(c.isalpha() for c in text): continue
            key = normalise_key(text[:60])
            if len(text) > cm: bq.add(key)
            else: cit.add(key)
    return bq, cit

def build_verse_map(pdf_path, cfg, body_size, page_range=None):
    import fitz
    vm = {}; doc = fitz.open(str(pdf_path))
    pages = range(doc.page_count) if page_range is None else [p for p in page_range if p < doc.page_count]
    sig = cfg.get("verse_label_signature",[])
    if not sig: return vm
    for pi in pages:
        for block in doc[pi].get_text("dict", sort=True)["blocks"]:
            if block.get("type") != 0: continue
            wr = set()
            for line in block.get("lines",[]):
                for span in line.get("spans",[]):
                    if span["text"].strip(): wr.add((font_weight(span["font"]), size_bucket(span["size"]) / body_size))
            if not all(any(_match_rule(w,r,rule) for w,r in wr) for rule in sig): continue
            lo = []; vn = None
            for line in block.get("lines",[]):
                lt = "".join(s["text"] for s in line.get("spans",[])).strip()
                if not lt: continue
                m = re.match(r"^VERSE\s*(\d+)\s*(.*)", lt, re.IGNORECASE)
                if m and vn is None: vn = m.group(1); rest = m.group(2).strip(); (lo.append(rest) if rest else None)
                elif vn is not None: lo.append(lt)
            if vn and lo and vn not in vm: vm[vn] = lo
    return vm

def build_inline_bold_set(pdf_path, cfg, body_size, page_range=None):
    import fitz
    doc = fitz.open(str(pdf_path))
    pages = range(doc.page_count) if page_range is None else [p for p in page_range if p < doc.page_count]
    phrases = set()
    for pi in pages:
        for block in doc[pi].get_text("dict", sort=True)["blocks"]:
            if block.get("type") != 0: continue
            hr = hb = False
            for line in block.get("lines",[]):
                for span in line.get("spans",[]):
                    if not span["text"].strip(): continue
                    if size_bucket(span["size"]) != body_size: continue
                    if "bold" in span["font"].lower(): hb = True
                    else: hr = True
            if not (hb and hr): continue
            for line in block.get("lines",[]):
                for span in line.get("spans",[]):
                    if not span["text"].strip(): continue
                    if size_bucket(span["size"]) == body_size and "bold" in span["font"].lower():
                        p = span["text"].strip()
                        if 5 <= len(p) <= 50: phrases.add(p)
    return sorted(phrases, key=len, reverse=True)

def build_callout_set(pdf_path, cfg, body_size, page_range=None):
    import fitz
    doc = fitz.open(str(pdf_path))
    pages = range(doc.page_count) if page_range is None else [p for p in page_range if p < doc.page_count]
    sig = cfg.get("callout_signature",[])
    if not sig: return []
    ct = []
    for pi in pages:
        pb = []
        for block in doc[pi].get_text("dict", sort=True)["blocks"]:
            if block.get("type") != 0: continue
            wr = set(); text = ""
            for line in block.get("lines",[]):
                for span in line.get("spans",[]):
                    if span["text"].strip(): wr.add((font_weight(span["font"]), size_bucket(span["size"]) / body_size))
                    text += span["text"]
            text = " ".join(text.split()).strip()
            if not text or not wr: continue
            pb.append((all(any(_match_rule(w,r,rule) for rule in sig) for w,r in wr), text))
        cur = []
        for ic, text in pb:
            if ic: cur.append(text)
            else:
                if cur: j = " ".join(cur); (ct.append(j) if len(j) > 15 else None); cur = []
        if cur: j = " ".join(cur); (ct.append(j) if len(j) > 15 else None)
    return sorted(set(ct), key=len, reverse=True)

def dump_fonts(pdf_path, page_range=None):
    import fitz
    doc = fitz.open(str(pdf_path))
    pages = range(doc.page_count) if page_range is None else [p for p in page_range if p < doc.page_count]
    freq = {}; samples = {}
    for pi in pages:
        for block in doc[pi].get_text("dict")["blocks"]:
            if block.get("type") != 0: continue
            for line in block.get("lines",[]):
                for span in line.get("spans",[]):
                    t = span["text"].strip()
                    if any(c.isalpha() for c in t):
                        k = (span["font"], size_bucket(span["size"])); freq[k] = freq.get(k,0) + len(t)
                        if k not in samples: samples[k] = t[:50]
    bf, bs = max(freq, key=freq.get)
    print(f"\nBody font: {bf} @ {bs}pt")
    print(f"\n{'Font':<40} {'Size':>6} {'Ratio':>6} {'Weight':>10} {'Chars':>8}  Sample")
    print("-"*100)
    for (f,s),c in sorted(freq.items(), key=lambda x:-x[1]):
        print(f"{f:<40} {s:>6.1f} {s/bs:>6.2f} {font_weight(f):>10} {c:>8}  {samples.get((f,s),'')}")
    print(f"\nTotal: {len(freq)} font+size combinations")

# ---- Post-processing passes ----

def fix_headings(markdown, heading_map, skip_set, heading_order=None):
    lines = markdown.splitlines(); line_level = {}
    if heading_order:
        hoi = 0
        for i, line in enumerate(lines):
            m = re.match(r'^(#{1,6})\s+(.+)$', line)
            if m:
                cc = re.sub(r'^\*\*(.+)\*\*$', r'\1', m.group(2).strip())
                cc = re.sub(r'^\*(.+)\*$', r'\1', cc.strip()); clean = normalise_key(cc)
                if clean in skip_set: continue
                for j in range(hoi, len(heading_order)):
                    ho_key = normalise_key(heading_order[j][0])
                    if ho_key in skip_set: continue
                    if ho_key == clean: line_level[i] = heading_order[j][1]; hoi = j + 1; break
            else:
                stripped = line.strip(); bm = re.match(r'^\*\*(.+?)\*\*$', stripped)
                if bm:
                    clean = normalise_key(bm.group(1))
                    if clean in skip_set: continue
                    for j in range(hoi, len(heading_order)):
                        ho_key = normalise_key(heading_order[j][0])
                        if ho_key in skip_set: continue
                        if ho_key == clean: line_level[i] = heading_order[j][1]; hoi = j + 1; break
    occ = {}
    def _gl(key):
        if key not in heading_map: return None
        levels = heading_map[key]; idx = occ.get(key, 0); occ[key] = idx + 1
        return levels[min(idx, len(levels)-1)]
    out = []
    for i, line in enumerate(lines):
        if normalise_key(re.sub(r"[#>]","",line)) in skip_set: continue
        m = re.match(r'^(#{1,6})\s+(.+)$', line)
        if m:
            content = m.group(2)
            cc = re.sub(r'^\*\*(.+)\*\*$', r'\1', content.strip())
            cc = re.sub(r'^\*(.+)\*$', r'\1', cc.strip()); clean = normalise_key(cc)
            if clean in skip_set: continue
            was_bold = content.strip().startswith('**') and content.strip().endswith('**')
            level = (line_level[i], _gl(clean))[0] if i in line_level else _gl(clean)
            if i in line_level: _gl(clean)
            if level: out.append(f"{level} {cc}")
            else: out.append(f"**{cc}**" if was_bold else cc)
        else:
            stripped = line.strip(); bm = re.match(r'^\*\*(.+?)\*\*$', stripped)
            if bm:
                inner = bm.group(1); clean = normalise_key(inner)
                if i in line_level: level = line_level[i]; _gl(clean)
                else: level = _gl(clean)
                if level: out.append(f"{level} {inner}"); continue
            bc = normalise_key(line); level = _gl(bc)
            if level and stripped and len(stripped) > 2: out.append(f"{level} {stripped}")
            else: out.append(line)
    return '\n'.join(out)

def fix_verse_labels(markdown, verse_map):
    if not verse_map:
        return re.sub(r'^(?:#{1,6}\s+)?\*?\*?VERSE\s+(\d+)\*?\*?\s*$',
            lambda m: f"###### Verse {m.group(1)}", markdown, flags=re.MULTILINE|re.IGNORECASE)
    lines = markdown.splitlines(); out = []; i = 0; used = set()
    while i < len(lines):
        line = lines[i]; m = re.match(r'^(?:#{1,6}\s+)?\*?\*?VERSE\s+(\d+)\*?\*?\s*$', line, re.IGNORECASE)
        if m:
            vn = m.group(1); out.append(f"###### Verse {vn}")
            if vn in verse_map and vn not in used:
                out.append(""); vl = verse_map[vn]
                for j,v in enumerate(vl): out.append(f"{v}  " if j < len(vl)-1 else v)
                out.append(""); used.add(vn); i += 1
                while i < len(lines):
                    nl = lines[i].strip()
                    if nl.startswith('#') or re.match(r'^\*?\*?VERSE\s+\d+', nl, re.IGNORECASE): break
                    i += 1
                continue
            else: out.append("")
        else: out.append(line)
        i += 1
    return '\n'.join(out)

def fix_double_blockquote_citations(md): return re.sub(r'^> > (.+)$', r'<< \1', md, flags=re.MULTILINE)
def fix_blockquotes(md, bq_set, cit_set):
    lines = md.splitlines(); out = []
    for line in lines:
        s = line.strip()
        if not s or line.startswith('>') or line.startswith('<<') or line.startswith('#'): out.append(line); continue
        k = normalise_key(s[:60])
        if k in bq_set: out.append(f"> {s}")
        elif k in cit_set: out.append(f"<< {s}")
        else: out.append(line)
    return '\n'.join(out)
def fix_citations(md, cfg):
    pats = cfg.get("_citation_res",[]); cm = cfg.get("citation_max_chars",80)
    lines = md.splitlines(); out = []
    for i,line in enumerate(lines):
        s = line.strip()
        if not s or s.startswith('#') or s.startswith('>') or s.startswith('<<') or s.startswith('-') or s.startswith('*') or len(s)>120: out.append(line); continue
        pb = (i==0) or (lines[i-1].strip()==''); nb = (i==len(lines)-1) or (lines[i+1].strip()=='')
        if not (pb and nb): out.append(line); continue
        if any(p.match(s) for p in pats): out.append(f"<< {s}"); continue
        pc = next((lines[j].strip() for j in range(i-1,-1,-1) if lines[j].strip()),"")
        if (pc.startswith('>') or pc.startswith('<<')) and len(s)<cm: out.append(f"<< {s}"); continue
        out.append(line)
    return '\n'.join(out)
def fix_bullet_numbers(md): return re.sub(r'^- (\d+\.)\s', r'\1 ', md, flags=re.MULTILINE)
def fix_hyphenation(md):
    lines = md.splitlines(); out = []; i = 0
    while i < len(lines):
        line = lines[i]
        if line.rstrip().endswith('-') and len(line.strip()) > 5:
            j = i+1
            while j < len(lines) and not lines[j].strip(): j += 1
            if j < len(lines):
                nl = lines[j].lstrip()
                if nl and nl[0].islower() and not nl.startswith('#'): out.append(line.rstrip()[:-1] + lines[j].lstrip()); i = j+1; continue
        out.append(line); i += 1
    return '\n'.join(out)
def fix_pullquote_fragments(md):
    lines = md.splitlines(); out = []
    for line in lines:
        if line.startswith(' ') and len(line.strip()) < 120 and line.strip():
            s = line.strip()
            if not any(s.startswith(c) for c in ['-','*','#','>']): continue
        out.append(line)
    return '\n'.join(out)
def fix_missing_headings(md, heading_order, skip_set):
    if not heading_order: return md
    lines = md.splitlines(); output_heads = []
    for i, line in enumerate(lines):
        m = re.match(r'^(#{1,6})\s+(.+)$', line)
        if m: output_heads.append((i, normalise_key(m.group(2))))
    if not output_heads: return md
    out_len = len(output_heads)
    ho_h1s = [(hi, normalise_key(t)) for hi, (t, l) in enumerate(heading_order) if l == '#' and normalise_key(t) not in skip_set]
    out_h1s = [(oi, output_heads[oi][1]) for oi in range(out_len) if lines[output_heads[oi][0]].startswith('# ') and not lines[output_heads[oi][0]].startswith('## ')]
    oj = 0; anchor_pairs = []
    for ho_hi, ho_key in ho_h1s:
        for j in range(oj, len(out_h1s)):
            if out_h1s[j][1] == ho_key: anchor_pairs.append((ho_hi, out_h1s[j][0])); oj = j + 1; break
    anchor_ho = [ap[0] for ap in anchor_pairs]; anchor_out = [ap[1] for ap in anchor_pairs]
    segments = []
    if anchor_ho and anchor_ho[0] > 0: segments.append((0, anchor_ho[0], 0, anchor_out[0]))
    for k in range(len(anchor_ho)):
        ho_end = anchor_ho[k+1] if k+1 < len(anchor_ho) else len(heading_order)
        out_end = anchor_out[k+1] if k+1 < len(anchor_out) else out_len
        segments.append((anchor_ho[k], ho_end, anchor_out[k], out_end))
    matched = [None] * len(heading_order)
    for ho_start, ho_end, out_start, out_end in segments:
        oi = out_start
        for hi in range(ho_start, ho_end):
            key = normalise_key(heading_order[hi][0])
            if key in skip_set: matched[hi] = (True, -1); continue
            found = -1
            for j in range(oi, out_end):
                if output_heads[j][1] == key: found = output_heads[j][0]; oi = j + 1; break
            matched[hi] = (found >= 0, found)
    for hi in range(len(matched)):
        if matched[hi] is None: matched[hi] = (False, -1)
    seg_end_line = {}
    for ho_start, ho_end, out_start, out_end in segments:
        end_line = output_heads[out_end - 1][0] if out_end > 0 else len(lines)
        for hi in range(ho_start, ho_end): seg_end_line[hi] = end_line
    insertions = {}
    for hi, (orig, level) in enumerate(heading_order):
        is_found, _ = matched[hi]
        if is_found: continue
        key = normalise_key(orig)
        if key in skip_set: continue
        bound = seg_end_line.get(hi, len(lines)); insert_before = None
        for fhi in range(hi + 1, len(heading_order)):
            is_f, li = matched[fhi]
            if is_f and li >= 0 and li <= bound: insert_before = li; break
        if insert_before is not None:
            actual = insert_before
            while actual > 0:
                prev = lines[actual - 1].strip()
                if not prev: actual -= 1
                elif prev.startswith('*') and prev.endswith('*') and len(prev) > 30: actual -= 1
                else: break
            if actual not in insertions: insertions[actual] = []
            insertions[actual].append(f"{level} {orig}")
    if not insertions: return md
    out = []
    for i, line in enumerate(lines):
        if i in insertions:
            for h in insertions[i]: out.append(""); out.append(h)
        out.append(line)
    return '\n'.join(out)
def fix_missing_section_headings(md, cfg):
    ins = cfg.get("missing_section_headings",[])
    if not ins: return md
    ie = [e for e in ins if "italic_snippet" in e]; be = [e for e in ins if "before_heading" in e]
    lines = md.splitlines(); out = []
    for i,line in enumerate(lines):
        s = line.strip()
        for entry in be:
            if s == entry["before_heading"].strip():
                h = entry["heading"]; ht = re.sub(r'^#+\s+','',h).strip().lower()
                prev = '\n'.join(lines[max(0,i-6):i]).lower()
                if ht not in prev: out.append(""); out.append(h); [out.append(x) for x in entry.get("insert_lines",[])]; (out.append("") if entry.get("insert_lines") else None)
                break
        if s.startswith('*') and s.endswith('*') and len(s) > 30:
            tl = s.lower()
            for entry in ie:
                if entry["italic_snippet"].lower() in tl:
                    h = entry["heading"]; ht = re.sub(r'^#+\s+','',h).strip().lower()
                    prev = '\n'.join(lines[max(0,i-6):i]).lower()
                    if ht not in prev: out.append(""); out.append(h)
                    break
        out.append(line)
    return '\n'.join(out)
def fix_discussion_question_groups(md, cfg):
    lc = cfg.get("discussion_question_labels",[])
    if not lc: return md
    md = re.sub(r'\n+\*\*[A-Z][A-Z\s]+\*\*\n+(?=\n*#{1,4}\s+Discussion)', '\n\n', md)
    lines = md.splitlines(); out = []; indq = False; gc = 0
    for line in lines:
        if re.match(r'^####\s+\*?\*?Discussion Questions\*?\*?', line, re.IGNORECASE): indq = True; gc = 0; out.append(line); continue
        if indq and re.match(r'^#{1,4}\s+', line) and not re.match(r'^#{5,}', line): indq = False
        if indq and re.match(r'^1\.\s+', line) and gc < len(lc):
            if gc > 0: out.append('')
            out.append(lc[gc]); out.append(''); gc += 1
        out.append(line)
    return '\n'.join(out)
def fix_structural_labels(md):
    lines = md.splitlines(); out = []
    for line in lines:
        s = line.strip()
        if re.match(r'^#{1,6}\s+[A-Z][A-Z\s]+$', s): continue
        if re.match(r'^\*\*[A-Z][A-Z\s]+\*\*$', s): continue
        if re.match(r'^<<\s+\*\*[A-Z\s]+\*\*$', s): continue
        if re.match(r'^\*\*[A-Z]\*\*$', s): continue
        if re.match(r'^\*".+\.\.\.\*$', s): continue
        if s == '\u2022': continue
        if re.match(r'^#{1,6}\s+\w.*:$', s): out.append(re.sub(r'^#{1,6}\s+', '', line)); continue
        if s.startswith('\u2022'): out.append(re.sub(r'^\u2022\s*', '- ', line)); continue
        out.append(line)
    return '\n'.join(out)
def fix_dedup_headings(md):
    lines = md.splitlines(); out = []; prev = ""
    for line in lines:
        if re.match(r'^#{1,6}\s+', line.strip()):
            if line.strip() == prev: continue
            prev = line.strip()
        elif line.strip(): prev = ""
        out.append(line)
    return '\n'.join(out)
def fix_bold_bullets(md):
    lines = md.splitlines(); out = []
    for line in lines:
        s = line.strip(); m = re.match(r'^\*\*[\u2022\u00b7]\s*(.+?)\*\*(.*)', s)
        if m: out.append(f"- **{m.group(1).strip()}**{m.group(2)}"); continue
        out.append(line)
    return '\n'.join(out)
def fix_inline_bold(md, bold_phrases):
    if not bold_phrases: return md
    lines = md.splitlines(); out = []
    for line in lines:
        if not (re.match(r'^\d+\.\s', line.strip()) or line.strip().startswith('- ')): out.append(line); continue
        for p in bold_phrases:
            if f"**{p}**" in line: continue
            line = re.sub(r'(?<!\*)\b' + re.escape(p) + r'\b(?!\*)', f'**{p}**', line)
        out.append(line)
    return '\n'.join(out)
def _normalise_for_callout_match(text):
    t = text.replace("\u2019","'").replace("\u2018","'").replace("\u201c",'"').replace("\u201d",'"')
    return " ".join(t.replace("\u2014"," ").replace("\u2013"," ").split()).strip()
def _callout_regex(ct):
    pat = re.escape(ct.rstrip('.')); _EM = "\u2014"
    pat = pat.replace(re.escape(_EM), "\\s*[" + _EM + "\u2014]?\\s*")
    pat = pat.replace(re.escape("\u2019"), "['\u2019]").replace(re.escape("\u2018"), "['\u2018]")
    return re.compile(pat)
def fix_callouts(md, callout_texts):
    if not callout_texts: return md
    normalized = [(ct, _normalise_for_callout_match(ct)) for ct in callout_texts]
    regexes = [(ct, nc, _callout_regex(ct)) for ct, nc in normalized]
    lines = md.splitlines(); out = []
    for line in lines:
        s = line.strip()
        if s and len(s) < 120 and not s.startswith('#') and not s.startswith('>') and not s.startswith('<<'):
            nl = _normalise_for_callout_match(s)
            if any(nl == nc or nl == nc.rstrip('.') for _, nc, _ in regexes): continue
        out.append(line)
    for idx in range(len(out)):
        line = out[idx]
        if not line or line.startswith('#') or line.startswith('>') or line.startswith('<<') or line.startswith('-'): continue
        for ct, nc, rx in regexes:
            m = rx.search(out[idx])
            if m: out[idx] = out[idx][:m.start()] + f"<Callout>{m.group()}</Callout>" + out[idx][m.end():]
    return '\n'.join(out)
def fix_empty_tables(md, threshold=0.7):
    lines = md.splitlines(); out = []; i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith('|') and i+1 < len(lines) and '|---' in lines[i+1]:
            table = []
            while i < len(lines) and lines[i].strip().startswith('|'): table.append(lines[i]); i += 1
            total = empty = 0
            for tl in table:
                if '---' in tl: continue
                for cell in tl.strip().strip('|').split('|'): total += 1; empty += (not cell.strip())
            if total > 0 and empty / total >= threshold: continue
            out.extend(table)
        else: out.append(line); i += 1
    return '\n'.join(out)
def fix_final_review_table(md, cfg):
    rules = cfg.get("table_to_list",[])
    if not rules: return md
    lines = md.splitlines(); out = []; i = 0
    while i < len(lines):
        line = lines[i]; mr = None
        if line.strip().startswith('|') and i+1 < len(lines) and '|---' in lines[i+1]:
            for rule in rules:
                if rule["header_contains"] in line: mr = rule; break
        if mr:
            out.append(mr["output_heading"]); out.append(""); i += 2
            while i < len(lines) and lines[i].strip().startswith('|'):
                cells = [c.strip() for c in lines[i].strip().strip('|').split('|')]
                cell = cells[0] if cells else ''
                if cell and not cell.startswith('---'):
                    text = re.sub(r'<br\s*/?>', ' ', cell).strip()
                    m2 = re.match(r'^(\d+)\.\s+(.+)', text)
                    if m2: out.append(f"{m2.group(1)}. {m2.group(2)}")
                i += 1
            out.append(""); continue
        out.append(line); i += 1
    return '\n'.join(out)
def fix_junk_content(md, cfg):
    lp = [re.compile(p) for p in cfg.get("skip_line_patterns",[])]
    tm = cfg.get("skip_table_markers",[])
    lines = md.splitlines(); out = []; i = 0
    while i < len(lines):
        line = lines[i]; s = line.strip()
        if any(p.match(s) for p in lp): i += 1; continue
        if s.startswith('|') and any(m in s for m in tm):
            while i < len(lines) and lines[i].strip().startswith('|'): i += 1
            continue
        out.append(line); i += 1
    return '\n'.join(out)
def fix_artwork_images(md):
    art_pat = re.compile(
        r'^(?:<<\s+)?(?:Source:\s+)?'
        r'(\w[\w\s]*?),\s+'
        r'[\w\s.\u00c0-\u017f\-]+?\.\s+'
        r'(?:\*([^*]+)\*|([A-Z][^.]+?))'
        r'\.\s+\d{4}')
    def _filename(lastname, title):
        name = lastname.strip().split()[-1].lower()
        slug = re.sub(r'[^a-z0-9]+', '_', title.lower()).strip('_')
        return f"{name}_{slug}"
    lines = md.splitlines(); out = []; seen = set()
    for line in lines:
        s = line.strip()
        clean = re.sub(r'^<<\s+', '', s)
        clean = re.sub(r'^Source:\s+', '', clean)
        m = art_pat.match(clean) if not art_pat.match(s) else art_pat.match(s)
        if m:
            lastname = m.group(1); title = (m.group(2) or m.group(3)).strip()
            fn = _filename(lastname, title)
            if fn not in seen:
                out.append(f"![{title}]({fn})")
                out.append("")
                seen.add(fn)
            citation = re.sub(r'^<<\s+', '', s)
            out.append(f"<< {citation}")
        else: out.append(line)
    return '\n'.join(out)
def fix_toc_tables(md):
    lines = md.splitlines(); out = []; i = 0
    while i < len(lines):
        if lines[i].strip().startswith('|') and i+1 < len(lines) and '|---' in lines[i+1]:
            table = []
            while i < len(lines) and lines[i].strip().startswith('|'): table.append(lines[i]); i += 1
            data_rows = [t for t in table if '---' not in t]
            pn = sum(1 for t in data_rows if re.match(r'^[ivxlc]+$|^\d{1,3}$', [c.strip() for c in t.strip().strip('|').split('|')][-1]))
            if data_rows and pn >= len(data_rows) * 0.8: continue
            out.extend(table)
        else: out.append(lines[i]); i += 1
    return '\n'.join(out)
def fix_heading_fragments(md):
    lines = md.splitlines(); remove = set()
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith('# ') and not s.startswith('## '):
            h1_text = s[2:].strip().lower()
            if len(h1_text) < 4: continue
            for j in range(i+1, min(i+7, len(lines))):
                m = re.match(r'^(#{2,6})\s+(.+)$', lines[j].strip())
                if m:
                    lower = m.group(2).strip().lower()
                    if (lower.startswith(h1_text) or lower.endswith(h1_text)) and lower != h1_text: remove.add(i); break
        if s and not s.startswith('#') and not s.startswith('>') and not s.startswith('<<') and not s.startswith('-') and not s.startswith('*') and not s.startswith('|') and not s.startswith('<Callout') and not s.startswith('!['):
            prev_blank = (i == 0) or not lines[i-1].strip(); next_blank = (i+1 >= len(lines)) or not lines[i+1].strip()
            if prev_blank and next_blank and len(s) < 40:
                for j in range(i+1, min(i+4, len(lines))):
                    if lines[j].strip().startswith('# ') and not lines[j].strip().startswith('## '): remove.add(i); break
    if not remove: return md
    return '\n'.join(l for i, l in enumerate(lines) if i not in remove)

