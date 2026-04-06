"""Diagnose italic truncated scripture snippet that's not being filtered"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from run import *

BASE = os.path.dirname(__file__)
PDF = os.path.join(BASE, "2026-04-03 HomeStead-Interior-Affinity Design-v1.001.pdf")
RAW = os.path.join(BASE, "2026-04-03 HomeStead-Interior-Affinity Design-v1.001.raw.md")

out = []
out.append("=== 1. RAW MARKER around 'filled with wisdom' ===")
with open(RAW, encoding='utf-8') as f:
    for i, line in enumerate(f):
        if 'filled with wisdom' in line:
            out.append(f"  Line {i+1}: {repr(line.rstrip()[:120])}")

out.append("\n=== 2. PyMuPDF font data for 'filled with wisdom' ===")
import fitz
doc = fitz.open(PDF)
for pi in range(doc.page_count):
    for block in doc[pi].get_text("dict", sort=True)["blocks"]:
        if block.get("type") != 0: continue
        full = ""
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                full += span["text"]
        if 'filled with wisdom' not in full: continue
        out.append(f"\n  Page {pi+1}:")
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                sz = size_bucket(span["size"])
                w = font_weight(span["font"])
                out.append(f"    {w} {sz}pt ratio={sz/10.0:.2f} | {repr(span['text'][:80])}")

out.append("\n=== 3. All italic truncated snippets in raw (both patterns) ===")
import re
with open(RAW, encoding='utf-8') as f:
    for i, line in enumerate(f):
        s = line.strip()
        # Existing A5: *"...text...*  (quote at start, ellipsis at end)
        if re.match(r'^\*".+\.\.\.\*$', s):
            out.append(f"  A5 MATCH  line {i+1}: {s[:80]}")
        # Reverse: *...text"*  (ellipsis at start, quote at end)
        elif re.match(r'^\*\.\.\..*"\*$', s):
            out.append(f"  REVERSE   line {i+1}: {s[:80]}")
        # Any other standalone italic line with ellipsis
        elif s.startswith('*') and s.endswith('*') and '...' in s and len(s) < 120:
            out.append(f"  OTHER     line {i+1}: {s[:80]}")

out.append("\n=== 4. Current output around this line ===")
mds = sorted([f for f in os.listdir(BASE) if f.endswith('.md') and not f.endswith('.raw.md')],
             key=lambda f: os.path.getmtime(os.path.join(BASE, f)))
latest = os.path.join(BASE, mds[-1])
with open(latest, encoding='utf-8') as f:
    lines = f.readlines()
for i, line in enumerate(lines):
    if 'filled with wisdom' in line:
        for j in range(max(0,i-2), min(len(lines),i+3)):
            out.append(f"  {j+1:4d}: {lines[j].rstrip()[:100]}")

with open(os.path.join(BASE, "diag_italic_snippet.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print(f"Written to testing/diag_italic_snippet.txt")
