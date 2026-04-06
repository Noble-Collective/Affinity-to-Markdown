"""Diagnose callout detection issues - output to file for Claude to read"""
import os, sys, re
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from run import (load_template, detect_body_font, build_callout_set,
                 _normalise_for_callout_match, _callout_regex, normalise_key,
                 size_bucket, font_weight)
from pathlib import Path

BASE = os.path.dirname(__file__)
PDF = os.path.join(BASE, "2026-04-03 HomeStead-Interior-Affinity Design-v1.001.pdf")
RAW = os.path.join(BASE, "2026-04-03 HomeStead-Interior-Affinity Design-v1.001.raw.md")
mds = sorted([f for f in os.listdir(BASE) if f.endswith('.md') and not f.endswith('.raw.md')],
             key=lambda f: os.path.getmtime(os.path.join(BASE, f)))
OUT = os.path.join(BASE, mds[-1])
print(f"Reading output: {os.path.basename(OUT)}")

out = []

# 1. What callouts does build_callout_set detect?
cfg = load_template("homestead")
bfn, bs = detect_body_font(Path(PDF))
ct = build_callout_set(Path(PDF), cfg, bs)
out.append(f"=== 1. CALLOUT SET ({len(ct)} callouts) ===")
for i, c in enumerate(ct):
    out.append(f"  [{i}] ({len(c)} chars) {c[:100]}{'...' if len(c)>100 else ''}")

# 2. Check ALL <Callout> tags in output vs callout set size
with open(OUT, encoding='utf-8') as f:
    content = f.read()
callout_tags = re.findall(r'<Callout>(.+?)</Callout>', content)
out.append(f"\n=== 2. CALLOUT TAGS IN OUTPUT ({len(callout_tags)} found, {len(ct)} expected) ===")
for t in callout_tags:
    out.append(f"  TAG: {t[:80]}{'...' if len(t)>80 else ''}")

# 3. Check which callouts are NOT matched in output
out.append(f"\n=== 3. UNMATCHED CALLOUTS ===")
for c in ct:
    nc = _normalise_for_callout_match(c)
    rx = _callout_regex(c)
    found_tag = bool(re.search(re.escape(nc[:30]), content))
    found_rx = bool(rx.search(content))
    
    # Check if standalone was removed
    lines = content.splitlines()
    standalone_present = any(_normalise_for_callout_match(l.strip()) == nc or 
                            _normalise_for_callout_match(l.strip()) == nc.rstrip('.')
                            for l in lines if l.strip())
    
    if not found_rx:
        out.append(f"\n  MISSING CALLOUT:")
        out.append(f"    Original:   {c[:100]}{'...' if len(c)>100 else ''}")
        out.append(f"    Normalised: {nc[:100]}{'...' if len(nc)>100 else ''}")
        out.append(f"    First 30 chars in output: {found_tag}")
        out.append(f"    Standalone still present: {standalone_present}")
        # Show regex pattern
        out.append(f"    Regex pattern: {rx.pattern[:100]}")

# 4. RAW Marker around 'For all believers'
out.append(f"\n=== 4. RAW MARKER: 'For all believers' context ===")
with open(RAW, encoding='utf-8') as f:
    raw_lines = f.readlines()
for i, line in enumerate(raw_lines):
    if 'For all believers' in line:
        start = max(0, i-2)
        end = min(len(raw_lines), i+8)
        for j in range(start, end):
            out.append(f"  {j+1:4d}: {repr(raw_lines[j].rstrip()[:120])}")
        out.append("")

# 5. OUTPUT around 'For all believers'  
out.append(f"\n=== 5. OUTPUT: 'For all believers' context ===")
with open(OUT, encoding='utf-8') as f:
    out_lines = f.readlines()
for i, line in enumerate(out_lines):
    if 'For all believers' in line or 'devoted to God is to' in line:
        start = max(0, i-2)
        end = min(len(out_lines), i+6)
        for j in range(start, end):
            out.append(f"  {j+1:4d}: {out_lines[j].rstrip()[:140]}")
        out.append("")

# 6. OUTPUT: lines with "One cannot exist"
out.append(f"\n=== 6. OUTPUT: 'One cannot exist' context ===")
for i, line in enumerate(out_lines):
    if 'One cannot exist' in line:
        start = max(0, i-3)
        end = min(len(out_lines), i+5)
        for j in range(start, end):
            out.append(f"  {j+1:4d}: {out_lines[j].rstrip()[:140]}")
        out.append("")

# 7. PyMuPDF: callout-signature blocks containing "devoted to God"
out.append(f"\n=== 7. PyMuPDF: callout blocks with 'devoted' or 'believers' ===")
import fitz
doc = fitz.open(PDF)
sig = cfg.get("callout_signature", [])
for pi in range(doc.page_count):
    for block in doc[pi].get_text("dict", sort=True)["blocks"]:
        if block.get("type") != 0: continue
        full = ""
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                full += span["text"]
        if 'devoted to God' not in full and 'believers' not in full.lower(): continue
        if len(full) > 200: continue  # skip body paragraphs
        wr = set()
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                if span["text"].strip():
                    wr.add((font_weight(span["font"]), size_bucket(span["size"]) / bs))
        out.append(f"  Page {pi+1}: {repr(full[:100])}")
        out.append(f"    Font weights/ratios: {wr}")

outpath = os.path.join(BASE, "diag_callouts.txt")
with open(outpath, "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print(f"Written to {outpath}")
