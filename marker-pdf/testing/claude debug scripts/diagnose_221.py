"""Diagnose why 2:21 becomes **2:21** instead of <sup>2:21</sup>
Traces through: raw markdown, PyMuPDF font data, inline bold set"""
import re, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from run import *

BASE = os.path.join(os.path.dirname(__file__))
RAW = os.path.join(BASE, "2026-04-03 HomeStead-Interior-Affinity Design-v1.001.raw.md")
PDF = os.path.join(BASE, "2026-04-03 HomeStead-Interior-Affinity Design-v1.001.pdf")

# 1. What does raw Marker output have?
print("=" * 70)
print("1. RAW MARKER OUTPUT around '2:21'")
print("=" * 70)
with open(RAW, encoding='utf-8') as f:
    raw_lines = f.readlines()
for i, line in enumerate(raw_lines):
    if '2:21' in line and 'circumcision' in line.lower():
        print(f"  Line {i+1}: {line.rstrip()[:120]}")
    elif '2:21' in line and len(line.strip()) < 30:
        print(f"  Line {i+1}: {line.rstrip()}")

# 2. What does PyMuPDF see for this verse number?
print("\n" + "=" * 70)
print("2. PyMuPDF FONT DATA for blocks containing '2:21' + 'circumcision'")
print("=" * 70)
import fitz
doc = fitz.open(PDF)
body_size = 10.0
for pi in range(doc.page_count):
    for block in doc[pi].get_text("dict", sort=True)["blocks"]:
        if block.get("type") != 0: continue
        full = ""
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                full += span["text"]
        if '2:21' not in full: continue
        if 'circumcision' not in full.lower() and len(full) < 30: continue
        print(f"\n  Page {pi+1}, block text: {full[:80]}...")
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                t = span["text"]
                if '2:21' in t or '22' in t or 'eight' in t.lower() or 'circumcision' in t.lower():
                    sz = size_bucket(span["size"])
                    w = font_weight(span["font"])
                    ratio = sz / body_size
                    print(f"    SPAN: size={sz} ratio={ratio:.2f} weight={w} font={span['font']}")
                    print(f"          text={repr(t[:60])}")

# 3. Is "2:21" in the inline bold set?
print("\n" + "=" * 70)
print("3. INLINE BOLD SET check")
print("=" * 70)
cfg = load_template("homestead")
bfn, bs = detect_body_font(Path(PDF))
ib = build_inline_bold_set(Path(PDF), cfg, bs)
matches = [p for p in ib if '2:21' in p or '2:22' in p]
print(f"  Bold phrases matching '2:21' or '2:22': {matches}")
print(f"  Total bold phrases: {len(ib)}")

# 4. Check heading_map for this text
print("\n" + "=" * 70)
print("4. HEADING MAP check")
print("=" * 70)
hm, ho = build_heading_map(Path(PDF), cfg, bs)
key = normalise_key("2:21")
print(f"  normalise_key('2:21') = '{key}'")
print(f"  In heading_map: {key in hm}")
for k, v in hm.items():
    if '2:21' in k or '2 21' in k:
        print(f"  Found key '{k}' -> {v}")

# 5. Check what other <sup> verse numbers look like vs 2:21
print("\n" + "=" * 70)
print("5. LATEST OUTPUT: how are verse numbers rendered near this passage?")
print("=" * 70)
mds = sorted([f for f in os.listdir(BASE) if f.endswith('.md') and not f.endswith('.raw.md')],
             key=lambda f: os.path.getmtime(os.path.join(BASE, f)))
OUT = os.path.join(BASE, mds[-1])
with open(OUT, encoding='utf-8') as f:
    out_lines = f.readlines()
for i, line in enumerate(out_lines):
    if '2:21' in line or ('circumcision' in line.lower() and 'eight' in line.lower()):
        start = max(0, i - 2)
        end = min(len(out_lines), i + 3)
        for j in range(start, end):
            print(f"  {j+1:4d}: {out_lines[j].rstrip()[:120]}")
        print()
