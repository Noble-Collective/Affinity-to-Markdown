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
    # Detect copyright pages (contain \u00a9 at small font) and exclude from bq/cit.
    # Copyright boilerplate shares the same small font as blockquotes but isn't quoted text.
    copyright_pages = set()
    for pi in pages:
        for block in doc[pi].get_text("dict", sort=True)["blocks"]:
            if block.get("type") != 0: continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    if "\u00a9" in span["text"] and size_bucket(span["size"]) / body_size <= mr:
                        copyright_pages.add(pi)
    for pi in pages:
        if pi in copyright_pages: continue
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
            key = normalise_key(text)
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
                if cur: j = " ".join(cur); j = re.sub(r'(\w)- ([a-z])', r'\1\2', j); (ct.append(j) if len(j) > 15 else None); cur = []
        if cur: j = " ".join(cur); j = re.sub(r'(\w)- ([a-z])', r'\1\2', j); (ct.append(j) if len(j) > 15 else None)
    return sorted(set(ct), key=len, reverse=True)

def build_rotated_subdivisions(pdf_path, cfg, body_size, page_range=None):
    """Detect rotated sidebar sub-division headings and their anchor
    (the first horizontal content heading on the same page)."""
    import fitz
    hcfg = cfg.get("heading_hierarchy", {})
    labels = hcfg.get("rotated_subdivision_labels", [])
    if not labels: return []
    def _na(s): return s.replace("\u2018","'").replace("\u2019","'")
    label_set = {_na(l.upper()) for l in labels}
    doc = fitz.open(str(pdf_path))
    pages = range(doc.page_count) if page_range is None else [p for p in page_range if p < doc.page_count]
    rules = cfg.get("headings", [])
    found = {}
    for pi in pages:
        for block in doc[pi].get_text("dict", sort=True)["blocks"]:
            if block.get("type") != 0: continue
            for line in block.get("lines", []):
                if line.get("dir", (1,0)) == (1,0): continue
                text = "".join(s["text"] for s in line.get("spans", [])).strip()
                key = _na(text.upper())
                if key in label_set and key not in found:
                    found[key] = (pi, text)
    results = []
    for key, (page_num, orig) in sorted(found.items(), key=lambda x: x[1][0]):
        page = doc[page_num]; anchor = None
        for block in page.get_text("dict", sort=True)["blocks"]:
            if block.get("type") != 0: continue
            for line in block.get("lines", []):
                if line.get("dir", (1,0)) != (1,0): continue
                for span in line.get("spans", []):
                    t = span["text"].strip()
                    if not t or len(t) < 3: continue
                    sz = size_bucket(span["size"]); ratio = sz / body_size; w = font_weight(span["font"])
                    for rule in rules:
                        if rule["weight"] == w and rule["min_ratio"] <= ratio <= rule["max_ratio"]:
                            anchor = t; break
                    if anchor: break
                if anchor: break
            if anchor: break
        if anchor:
            words = orig.split(); tw = []
            for i, w in enumerate(words):
                tw.append(w.capitalize() if (i == 0 or ':' in w or w.upper() not in ('AND','THE','OF','IN','A')) else w.lower())
            results.append((" ".join(tw), normalise_key(anchor), page_num))
    return results

def build_verse_superscript_set(pdf_path, cfg, body_size, page_range=None):
    """Detect small bold text that represents verse number superscripts.
    Returns set of strings (e.g. '2:21', '103:1') that Marker renders as
    bold but should be <sup>."""
    import fitz
    doc = fitz.open(str(pdf_path))
    pages = range(doc.page_count) if page_range is None else [p for p in page_range if p < doc.page_count]
    nums = set()
    for pi in pages:
        for block in doc[pi].get_text("dict", sort=True)["blocks"]:
            if block.get("type") != 0: continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    t = span["text"].strip()
                    if not t: continue
                    sz = size_bucket(span["size"])
                    if sz / body_size < 0.75 and "bold" in span["font"].lower():
                        if re.fullmatch(r'\d+[:\d\-\u2013]*', t):
                            nums.add(t)
    return nums

def build_right_aligned_citations(pdf_path, cfg, body_size, page_range=None):
    """Detect short, body-size, right-aligned text that Marker incorrectly
    blockquotes. Returns {normalise_key: [line1, line2, ...]} so
    fix_blockquotes can convert > to << with correct line breaks."""
    import fitz
    doc = fitz.open(str(pdf_path))
    pages = range(doc.page_count) if page_range is None else [p for p in page_range if p < doc.page_count]
    results = {}
    for pi in pages:
        page = doc[pi]; pw = page.rect.width
        for block in page.get_text("dict", sort=True)["blocks"]:
            if block.get("type") != 0: continue
            # Right-aligned: block left edge past 55% of page width
            if block["bbox"][0] < pw * 0.55: continue
            # Body-size font
            fc = {}
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    if span["text"].strip():
                        k = (span["font"], size_bucket(span["size"]))
                        fc[k] = fc.get(k, 0) + len(span["text"].strip())
            if not fc: continue
            _, ds = max(fc, key=fc.get)
            if ds != body_size: continue
            # Short text (citation-length)
            block_lines = []
            for line in block.get("lines", []):
                lt = "".join(s["text"] for s in line.get("spans", [])).strip()
                if lt: block_lines.append(lt)
            full = " ".join(block_lines)
            if not full or len(full) > 80: continue
            results[normalise_key(full)] = block_lines
    return results

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
def fix_blockquotes(md, bq_set, cit_set, right_aligned_map=None):
    lines = md.splitlines(); out = []
    for line in lines:
        s = line.strip()
        if not s or line.startswith('<<') or line.startswith('#'): out.append(line); continue
        if line.startswith('>'):
            # Re-evaluate Marker blockquotes: right-aligned body-size text → citations
            bq_content = re.sub(r'^>\s*', '', s)
            bq_key = normalise_key(bq_content)
            if right_aligned_map and bq_key in right_aligned_map:
                for rl in right_aligned_map[bq_key]:
                    out.append(f"<< {rl}")
            else:
                out.append(line)
            continue
        # Use normalise_key(s) not normalise_key(s[:60]) — normalise_key strips
        # markdown asterisks before windowing to 60 chars, so inline italic markers
        # (e.g. *everlasting*) don't shift the key relative to the raw PDF text.
        k = normalise_key(s)
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
        if (pc.startswith('>') or pc.startswith('<<')) and len(s) > 5 and len(s)<cm: out.append(f"<< {s}"); continue
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
    dhp = re.escape(cfg.get("discussion_heading_pattern", "Discussion Questions"))
    md = re.sub(rf'\n+\*\*[A-Z][A-Z\s]+\*\*\n+(?=\n*#{{1,4}}\s+{dhp})', '\n\n', md)
    lines = md.splitlines(); out = []; indq = False; gc = 0
    for line in lines:
        if re.match(rf'^####\s+\*?\*?{dhp}\*?\*?', line, re.IGNORECASE): indq = True; gc = 0; out.append(line); continue
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
        if re.fullmatch(r'\*\.\.\..*"\*', s): continue
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
    _STRUCT = ('#', '>', '<<', '-', '|', '![')
    lines = md.splitlines(); out = []
    # Phase 1: Remove standalone callout lines (exact match OR prefix of a callout)
    for line in lines:
        s = line.strip()
        if s and len(s) < 120 and not any(s.startswith(p) for p in _STRUCT):
            nl = _normalise_for_callout_match(s)
            if any(nl == nc or nl == nc.rstrip('.') for _, nc, _ in regexes): continue
        out.append(line)
    # Phase 2: Group consecutive body paragraphs separated by single blank
    # lines, join for cross-paragraph callout matching. This handles Marker
    # fragmenting body paragraphs at callout extraction points.
    result = []; i = 0
    while i < len(out):
        line = out[i]
        if line.strip() and not any(line.startswith(p) for p in _STRUCT):
            # Start a body paragraph group
            group_indices = [i]; j = i + 1
            while j < len(out):
                if not out[j].strip():  # blank line
                    if j+1 < len(out) and out[j+1].strip() and not any(out[j+1].startswith(p) for p in _STRUCT):
                        group_indices.append(j+1); j += 2; continue
                    break
                elif any(out[j].startswith(p) for p in _STRUCT): break
                else: group_indices.append(j); j += 1
            end = j
            joined = ' '.join(out[idx].strip() for idx in group_indices)
            matched = False
            for ct, nc, rx in regexes:
                m = rx.search(joined)
                if m:
                    joined = joined[:m.start()] + f'<Callout>{m.group()}</Callout>' + joined[m.end():]
                    matched = True
            if matched: result.append(joined)
            else:
                for k in range(i, end): result.append(out[k])
            i = end
        else: result.append(line); i += 1
    return '\n'.join(result)
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
        clean = re.sub(r'^>\s+', '', clean)
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
            citation = re.sub(r'^>\s+', '', citation)
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

def fix_front_matter(md, cfg):
    """Apply front matter corrections: remove specific lines and apply
    text replacements from config for title/copyright pages."""
    fm = cfg.get("front_matter_corrections")
    if not fm: return md
    lines = md.splitlines()
    end_marker = fm.get("ends_before", "")
    end_idx = len(lines)
    if end_marker:
        for i, line in enumerate(lines):
            if line.strip() == end_marker: end_idx = i; break
    remove_pats = [re.compile(p) for p in fm.get("remove_lines", [])]
    
    replacements = fm.get("text_replacements", [])
    out = []
    for i, line in enumerate(lines):
        if i < end_idx:
            s = line.strip()
            if any(p.search(s) for p in remove_pats): continue
            for rep in replacements:
                m = rep["match"]
                if s == m:
                    line = rep["replace"]; break
                elif s.startswith(m):
                    line = rep["replace"] + s[len(m):]; break
        out.append(line)
    return '\n'.join(out)
    

def fix_heading_hierarchy(md, cfg, heading_order=None):
    """Restructure heading levels from font-based to semantic hierarchy.
    Merges H1+H2 pairs into H4, shifts H3-H5 down one level, converts
    H6 verses to bold text. Inserts H1 Part, H2 Session, and H3
    sub-division headings. Cleans up misplaced and artifact headings."""
    hcfg = cfg.get("heading_hierarchy")
    if not hcfg: return md
    session_map = hcfg.get("session_map", [])
    parts = hcfg.get("parts", [])
    front_matter = hcfg.get("front_matter_label", "")
    trailing = hcfg.get("trailing_section")
    subdiv_labels = hcfg.get("subdivision_labels", [])
    text_fixes = hcfg.get("heading_text_fixes", [])
    remove_headings = {normalise_key(h) for h in hcfg.get("remove_artifact_headings", [])}
    # Build session word-to-digit map from session_map (e.g. "One"->"1")
    _session_nums = {}
    _scount = 0
    for _sn in session_map:
        if _sn and re.match(r'^Session ', _sn):
            _scount += 1
            _session_nums[_sn.split(' ', 1)[1]] = str(_scount)
    lines = md.splitlines()
    # Phase 1: Find H1s and H2 companions, build session structure
    h1s = []
    for i, line in enumerate(lines):
        if line.startswith('# ') and not line.startswith('## '):
            h2_idx = h2_text = None
            for j in range(i+1, min(i+5, len(lines))):
                if lines[j].startswith('## ') and not lines[j].startswith('### '):
                    h2_idx = j; h2_text = lines[j][3:].strip(); break
                elif lines[j].strip() and lines[j].strip()[0] == '#': break
            h1s.append({'line': i, 'text': line[2:].strip(), 'h2_line': h2_idx, 'h2_text': h2_text})
    h1_title_keys = [normalise_key(h['text']) for h in h1s]
    part_map = {p["before_session"]: p["label"] for p in parts}
    part_markers = [p.get("marker","") for p in parts if p.get("marker")]
    skip = set(); replace = {}; before = {}
    for idx, h1 in enumerate(h1s):
        if idx >= len(session_map): break
        sname = session_map[idx]
        pre = []
        if sname and sname in part_map: pre.extend(["", "# " + part_map[sname], ""])
        if sname: pre.extend(["## " + sname, ""])
        if pre: before[h1['line']] = pre
        if h1['h2_text']:
            clean = re.sub(r'^\*(.+)\*$', r'\1', h1['h2_text'])
            merged = "#### " + h1['text'] + ": " + clean
            for fix in text_fixes:
                if fix["match"] in merged:
                    merged = merged.replace(fix["match"], fix["replace"])
            replace[h1['line']] = merged
            skip.add(h1['h2_line'])
        elif sname is None: replace[h1['line']] = "### " + h1['text']
        else: replace[h1['line']] = "#### " + h1['text']
    if trailing:
        tname = trailing.get("session_name",""); tpart = trailing.get("part_label","")
        tmarker = trailing.get("subtitle_contains","")
        if tmarker:
            for i, line in enumerate(lines):
                if line.startswith('## ') and tmarker in line:
                    pre = []
                    if tpart: pre.extend(["", "# " + tpart, ""])
                    if tname: pre.extend(["## " + tname, ""])
                    if pre: before[i] = pre
                    clean = re.sub(r'^\*(.+)\*$', r'\1', line[3:].strip())
                    replace[i] = "#### " + tname + ": " + clean if tname else "#### " + clean
                    break
    # Remove PART text markers and repeated-word artifacts
    for i, line in enumerate(lines):
        s = line.strip()
        if i in replace or i in skip: continue
        for pm in part_markers:
            if pm in s and not s.startswith('#') and len(s) < 30: skip.add(i)
        _ts_name = trailing.get("session_name", "") if trailing else ""
        if _ts_name and re.match(rf'^({re.escape(_ts_name)}\s*)+$', s) and not s.startswith('#'): skip.add(i)
    # Phase 2: Build output with level shifts
    out = []
    if front_matter: out.extend(["# " + front_matter, ""])
    for i, line in enumerate(lines):
        if i in before: out.extend(before[i])
        if i in skip: continue
        if i in replace: out.append(replace[i]); continue
        m = re.match(r'^(#{1,6})\s+(.+)$', line)
        if m:
            lv = len(m.group(1)); tx = m.group(2)
            if normalise_key(tx) in remove_headings: continue
            if lv == 6: out.append("**" + tx + "**")
            elif 3 <= lv <= 5: out.append('#' * (lv + 1) + ' ' + tx)
            elif lv == 2: out.append("#### " + tx)
            else: out.append(line)
        else: out.append(line)
    # Phase 2b: Fix PART heading positioning.
    # Marker places Part intro paragraphs before the H1, but Phase 2 inserts
    # the # PART heading right before the H1. Result: intro paragraph appears
    # above the PART heading. Fix: scan backward from each # PART line, relocate
    # long body paragraphs (intro text) to after the PART+Session block, and
    # remove short stray text/headings (duplicates of content after PART).
    new_out = []; skip_lines = set(); inserts_after = {}
    for i, line in enumerate(out):
        if line.startswith('# PART '):
            # Scan backward: collect non-blank lines until artwork/citation/blockquote
            collected = []
            j = i - 1
            while j >= 0:
                l = out[j].strip()
                if not l: j -= 1; continue
                if l.startswith('<<') or l.startswith('![') or l.startswith('>'): break
                collected.append(j); j -= 1
            # Insert after the # PART heading itself
            insert_at = i
            # Classify: long paragraphs (>100 chars) = intro text to relocate;
            # everything else = stray artifacts to remove
            relocate_lines = []
            for idx in collected:
                if len(out[idx].strip()) > 100:
                    relocate_lines.append(out[idx])
                skip_lines.add(idx)
            if relocate_lines:
                inserts_after[insert_at] = relocate_lines
    if skip_lines or inserts_after:
        for i, line in enumerate(out):
            if i in skip_lines: continue
            new_out.append(line)
            if i in inserts_after:
                new_out.append('')
                for rl in inserts_after[i]: new_out.append(rl)
        out = new_out
    # Phase 3: Insert H3 sub-division headings from heading_order
    if heading_order and subdiv_labels:
        subdiv_keys = {normalise_key(s) for s in subdiv_labels}
        si = -1; sn = ""; subdivs = []
        for i, (text, level) in enumerate(heading_order):
            key = normalise_key(text)
            if level != '#': continue
            if key in subdiv_keys:
                for j in range(i+1, min(i+5, len(heading_order))):
                    nk = normalise_key(heading_order[j][0])
                    if nk not in subdiv_keys and heading_order[j][1] in ('###','####'):
                        subdivs.append((si, sn, text, nk)); break
            else:
                for ki in range(si+1, len(h1_title_keys)):
                    if h1_title_keys[ki] == key:
                        si = ki; sn = session_map[si] if si < len(session_map) else ""; break
        def _pfx(s):
            if not s: return ""
            m2 = re.match(r'^Session (\w+)$', s)
            return "Session " + _session_nums.get(m2.group(1), m2.group(1)) if m2 else s
        cur = -1; used = set(); new_out = []
        for line in out:
            if line.startswith('## ') and not line.startswith('### '): cur += 1
            hm2 = re.match(r'^(####)\s+(.+)$', line)
            if hm2 and cur >= 0:
                hkey = normalise_key(hm2.group(2))
                for s_i, s_n, sdtxt, akey in subdivs:
                    uid = (s_i, normalise_key(sdtxt))
                    if uid in used: continue
                    if s_i == cur and hkey == akey:
                        pfx = _pfx(s_n)
                        new_out.extend(["", ("### " + pfx + " " + sdtxt) if pfx else ("### " + sdtxt), ""])
                        used.add(uid); break
            new_out.append(line)
        out = new_out
    # Phase 3b: Insert rotated sidebar sub-division headings
    rotated = cfg.get("_rotated_subdivisions", [])
    if rotated:
        ri = 0; new_out = []
        for li, line in enumerate(out):
            if ri < len(rotated):
                hm2 = re.match(r'^(#{4,5})\s+(.+)$', line)
                if hm2 and normalise_key(hm2.group(2)) == rotated[ri][1]:
                    # Skip if a matching H2 session heading follows within a few lines
                    # (this anchor is at end of previous section, not inside correct session)
                    boundary = False
                    rkey = normalise_key(rotated[ri][0])
                    for j in range(li+1, min(li+8, len(out))):
                        al = out[j].strip()
                        if al.startswith('## ') and not al.startswith('### '):
                            if normalise_key(al[3:]) == rkey: boundary = True
                            break
                        if al.startswith('# ') and not al.startswith('## '):
                            boundary = True; break
                    if not boundary:
                        new_out.extend(["", "### " + rotated[ri][0], ""])
                        ri += 1
            new_out.append(line)
        out = new_out
    # Phase 3c: Config-driven subdivision overrides (for headings not auto-detected)
    overrides = hcfg.get("subdivision_overrides", [])
    if overrides:
        cur_session = ""; new_out = []
        for line in out:
            if line.startswith('## ') and not line.startswith('### '):
                cur_session = line[3:].strip()
            for ov in overrides:
                if cur_session == ov["session"]:
                    hm2 = re.match(r'^(####)\s+(.+)$', line)
                    if hm2 and normalise_key(hm2.group(2)) == normalise_key(ov["before_heading"]):
                        new_out.extend(["", "### " + ov["label"], ""])
                        overrides = [o for o in overrides if o is not ov]  # consume it
                        break
            new_out.append(line)
        out = new_out
    # Phase 4: Cleanup — remove misplaced headings and duplicate artifacts
    session_names = {normalise_key(s) for s in session_map if s}
    subdiv_text_keys = set()
    for sname in session_map:
        if not sname: continue
        m2 = re.match(r'^Session (\w+)$', sname)
        prefix = "Session " + _session_nums.get(m2.group(1), m2.group(1)) if m2 else sname
        for sl in subdiv_labels:
            subdiv_text_keys.add(normalise_key(prefix + " " + sl))
    for ov in hcfg.get("subdivision_overrides", []):
        subdiv_text_keys.add(normalise_key(ov["label"]))
    clean = []; i = 0
    while i < len(out):
        line = out[i]; s = line.strip()
        # Remove plain text sub-division labels that now duplicate H3 headings
        if s and not s.startswith('#') and not s.startswith('>') and not s.startswith('<') and normalise_key(s) in subdiv_text_keys:
            i += 1; continue
        # Remove misplaced H5 headings that appear just before their H2 container
        if s.startswith('##### '):
            h5_key = normalise_key(s[6:])
            if h5_key in session_names:
                misplaced = False
                for j in range(i+1, min(i+5, len(out))):
                    al = out[j].strip()
                    if al.startswith('## ') and not al.startswith('### '):
                        if normalise_key(al[3:]) == h5_key: misplaced = True
                        break
                    if al.startswith('# ') and not al.startswith('## '): misplaced = True; break
                if misplaced: i += 1; continue
        # Remove first of duplicate adjacent H4 headings (with gap tolerance)
        if s.startswith('#### '):
            h4_key = normalise_key(s[5:])
            found_dup = False
            for j in range(i+1, min(i+5, len(out))):
                al = out[j].strip()
                if al.startswith('#### ') and normalise_key(al[5:]) == h4_key:
                    found_dup = True; break
                if al.startswith('#') and not al.startswith('#### '): break
            if found_dup: i += 1; continue
        clean.append(line); i += 1
    return '\n'.join(clean)

def post_process(md, heading_map, skip_set, bq_set, cit_set, verse_map, cfg,
                 callout_texts=None, inline_bold=None, heading_order=None, verse_sup=None):
    md = md.replace('\r\n','\n').replace('\r','\n')
    md = re.sub(r'^!\[.*?\]\(.*?\)\s*$', '', md, flags=re.MULTILINE)
    md = re.sub(r'^-{20,}\s*$', '', md, flags=re.MULTILINE)
    skip_set = {k for k in skip_set if k not in heading_map or any(l == '#' for l in heading_map[k])}
    md = fix_pullquote_fragments(md)
    md = fix_headings(md, heading_map, skip_set, heading_order)
    md = fix_verse_labels(md, verse_map)
    md = fix_double_blockquote_citations(md)
    md = fix_blockquotes(md, bq_set, cit_set, cfg.get('_right_aligned_map'))
    md = fix_citations(md, cfg)
    md = fix_bullet_numbers(md)
    md = fix_hyphenation(md)
    md = fix_callouts(md, callout_texts or [])
    md = re.sub(r'</Callout>\s*<Callout>', ' ', md)
    md = fix_empty_tables(md)
    md = fix_toc_tables(md)
    md = fix_final_review_table(md, cfg)
    md = fix_inline_bold(md, inline_bold or [])
    md = fix_junk_content(md, cfg)
    md = fix_artwork_images(md)
    md = fix_missing_headings(md, heading_order or [], skip_set)
    md = fix_dedup_headings(md)
    md = fix_heading_fragments(md)
    md = fix_missing_section_headings(md, cfg)
    md = fix_discussion_question_groups(md, cfg)
    md = fix_structural_labels(md)
    md = fix_bold_bullets(md)
    md = re.sub(r'^<<\s+\*\*(.+?)\*\*', r'<< \1', md, flags=re.MULTILINE)
    md = fix_front_matter(md, cfg)
    md = fix_heading_hierarchy(md, cfg, heading_order)
    # Convert verse number superscripts: small bold text in PDF that Marker
    # renders as **X** or **<sup>X</sup>** should be plain <sup>X</sup>
    if verse_sup:
        for v in sorted(verse_sup, key=len, reverse=True):
            ev = re.escape(v)
            md = md.replace(f'**<sup>{v}</sup>**', f'<sup>{v}</sup>')
            md = re.sub(rf'\*\*{ev}\*\*', f'<sup>{v}</sup>', md)
    md = re.sub(r'(\*\*Verse \d+\*\*)\n\n', r'\1\n', md)
    md = re.sub(r'\n{3,}', '\n\n', md)
    return md.strip() + '\n'

# ---- Marker bug patch ----

def patch_block_relabel():
    from copy import deepcopy
    from marker.processors.block_relabel import BlockRelabelProcessor
    from marker.schema.registry import get_block_class
    def patched_call(self, document):
        if len(self.block_relabel_map) == 0: return
        for page in document.pages:
            for block in page.structure_blocks(document):
                if block.block_type not in self.block_relabel_map: continue
                ct, rt = self.block_relabel_map[block.block_type]
                conf = block.top_k.get(block.block_type)
                if conf is None or conf > ct: continue
                nc = get_block_class(rt)
                nb = nc(polygon=deepcopy(block.polygon), page_id=block.page_id,
                    structure=deepcopy(block.structure), text_extraction_method=block.text_extraction_method,
                    source="heuristics", top_k=block.top_k, metadata=block.metadata)
                page.replace_block(block, nb)
    BlockRelabelProcessor.__call__ = patched_call

def get_available_gemini_model(api_key):
    candidates = ["gemini-2.0-flash","gemini-2.0-flash-lite","gemini-1.5-flash","gemini-1.5-pro"]
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        avail = {m.name.split("/")[-1] for m in client.models.list()}
        for c in candidates:
            if c in avail: return c
    except Exception: pass
    return "gemini-2.0-flash"

# ---- Main ----

def main():
    ap = argparse.ArgumentParser(description="Convert PDF to Markdown.")
    ap.add_argument("input"); ap.add_argument("pdf", nargs="?"); ap.add_argument("output", nargs="?")
    ap.add_argument("--template", default="homestead"); ap.add_argument("--page-range", default="")
    ap.add_argument("--dump-fonts", action="store_true"); ap.add_argument("--save-raw", action="store_true")
    ap.add_argument("--postprocess", action="store_true")
    ap.add_argument("--verbose", action="store_true", help="Show detailed Marker/LLM logging")
    args = ap.parse_args()
    if args.verbose: logging.getLogger().setLevel(logging.INFO)

    page_range = None
    if args.page_range.strip():
        pages = []
        for part in args.page_range.split(","):
            part = part.strip()
            if "-" in part: s,e = part.split("-",1); pages.extend(range(int(s),int(e)+1))
            else: pages.append(int(part))
        page_range = pages

    if args.dump_fonts:
        p = Path(args.input)
        if not p.exists(): print(f"ERROR: {p}"); sys.exit(1)
        dump_fonts(p, page_range); return

    cfg = load_template(args.template)
    print(f"Template: {args.template}")

    if args.postprocess:
        rp = Path(args.input)
        if not rp.exists(): print(f"ERROR: {rp}"); sys.exit(1)
        if not args.pdf: print("ERROR: --postprocess requires PDF as second arg"); sys.exit(1)
        pp = Path(args.pdf)
        if not pp.exists(): print(f"ERROR: {pp}"); sys.exit(1)
        op = Path(args.output) if args.output else rp.with_suffix(".md")
        if op == rp: op = rp.with_stem(rp.stem + "_processed")
        bfn, bs = detect_body_font(pp, page_range)
        print(f"Body font: {bfn} @ {bs}pt")
        print("Building font maps...")
        hm, ho = build_heading_map(pp, cfg, bs, page_range)
        ss = build_skip_set(pp, cfg, bs, page_range)
        bq, ci = build_blockquote_set(pp, cfg, bs, page_range)
        vm = build_verse_map(pp, cfg, bs, page_range)
        ct = build_callout_set(pp, cfg, bs, page_range)
        ib = build_inline_bold_set(pp, cfg, bs, page_range)
        cfg["_rotated_subdivisions"] = build_rotated_subdivisions(pp, cfg, bs, page_range)
        cfg["_right_aligned_map"] = build_right_aligned_citations(pp, cfg, bs, page_range)
        vs = build_verse_superscript_set(pp, cfg, bs, page_range)
        print(f"  {len(hm)} headings, {len(ho)} ordered, {len(ss)} skips, "
              f"{len(bq)} bq, {len(ci)} cit, {len(vm)} verses, {len(ct)} callouts, {len(ib)} bold, {len(vs)} vsup.")
        raw = rp.read_text(encoding="utf-8")
        print("Post-processing...")
        md = post_process(raw, hm, ss, bq, ci, vm, cfg, ct, ib, ho, vs)
        op.write_text(md, encoding="utf-8")
        print(f"Done! {op} ({len(md.splitlines())} lines)")
        return

    pp = Path(args.input)
    if not pp.exists(): print(f"ERROR: {pp}"); sys.exit(1)
    op = Path(args.output) if args.output else pp.with_suffix(".md")
    bfn, bs = detect_body_font(pp, page_range)
    print(f"Body font: {bfn} @ {bs}pt")
    print("Building font maps...")
    hm, ho = build_heading_map(pp, cfg, bs, page_range)
    ss = build_skip_set(pp, cfg, bs, page_range)
    bq, ci = build_blockquote_set(pp, cfg, bs, page_range)
    vm = build_verse_map(pp, cfg, bs, page_range)
    ct = build_callout_set(pp, cfg, bs, page_range)
    ib = build_inline_bold_set(pp, cfg, bs, page_range)
    cfg["_rotated_subdivisions"] = build_rotated_subdivisions(pp, cfg, bs, page_range)
    cfg["_right_aligned_map"] = build_right_aligned_citations(pp, cfg, bs, page_range)
    vs = build_verse_superscript_set(pp, cfg, bs, page_range)
    print(f"  {len(hm)} headings, {len(ho)} ordered, {len(ss)} skips, "
          f"{len(bq)} bq, {len(ci)} cit, {len(vm)} verses, {len(ct)} callouts, {len(ib)} bold, {len(vs)} vsup.")

    patch_block_relabel()
    print("Loading models...")
    import torch
    from marker.models import create_model_dict
    models = create_model_dict(device="cpu", dtype=torch.float32)

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
    gak = os.environ.get("GOOGLE_API_KEY","")
    llm = None
    if gak:
        mn = get_available_gemini_model(gak)
        mcfg["gemini_api_key"] = gak; mcfg["gemini_model_name"] = mn
        llm = "marker.services.gemini.GoogleGeminiService"
        print(f"LLM enabled: {mn} (key: ...{gak[-4:]})")
    else:
        print("LLM disabled: no GOOGLE_API_KEY")
    if page_range: mcfg["page_range"] = page_range

    from marker.converters.pdf import PdfConverter
    print(f"Converting {pp.name}...")
    conv = PdfConverter(artifact_dict=models, processor_list=None, config=mcfg, llm_service=llm)
    rendered = conv(str(pp))
    if args.save_raw:
        rp2 = op.with_suffix(".raw.md"); rp2.write_text(rendered.markdown, encoding="utf-8")
        print(f"Raw saved: {rp2}")

    print("Post-processing...")
    md = post_process(rendered.markdown, hm, ss, bq, ci, vm, cfg, ct, ib, ho, vs)
    op.write_text(md, encoding="utf-8")
    print(f"Done! {op} ({len(md.splitlines())} lines)")

if __name__ == "__main__":
    main()
