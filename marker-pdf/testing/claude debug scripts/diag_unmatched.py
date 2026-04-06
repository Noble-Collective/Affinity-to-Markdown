"""Identify which callouts from the PDF are NOT tagged in the output"""
import os, sys, re
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from pathlib import Path
from run import load_template, detect_body_font, build_callout_set, _callout_regex, _callout_regex_relaxed

PDF = os.path.join(os.path.dirname(__file__), "2026-04-03 HomeStead-Interior-Affinity Design-v1.001.pdf")
# Find the latest output file (highest number in parentheses)
import glob
pattern = os.path.join(os.path.dirname(__file__), "2026-04-03 HomeStead-Interior-Affinity Design-v1.001 (*).md")
files = sorted(glob.glob(pattern))
OUT = files[-1] if files else os.path.join(os.path.dirname(__file__), "2026-04-03 HomeStead-Interior-Affinity Design-v1.001.raw_processed.md")
print(f"Using output: {os.path.basename(OUT)}")

cfg = load_template("homestead")
_, bs = detect_body_font(Path(PDF))
ct = build_callout_set(Path(PDF), cfg, bs)

with open(OUT, encoding='utf-8') as f:
    content = f.read()

print(f"Callout set: {len(ct)} items")
print(f"Tags in output: {content.count('<Callout>')}")

unmatched = []
matched = []
for c in ct:
    rx = _callout_regex(c)
    rx_r = _callout_regex_relaxed(c)
    if rx.search(content):
        matched.append(c)
    elif rx_r and rx_r.search(content):
        matched.append(c)
    else:
        unmatched.append(c)

print(f"\nMATCHED: {len(matched)}")
print(f"UNMATCHED: {len(unmatched)}")

for i, c in enumerate(unmatched):
    print(f"\n--- UNMATCHED {i+1} ---")
    print(f"  Text ({len(c)} chars): {c[:120]}")
    if len(c) > 120: print(f"  ...{c[-60:]}")
    
    # Try to find partial match in output
    words = c.split()[:6]
    snippet = ' '.join(words)
    for li, line in enumerate(content.splitlines()):
        if snippet.lower() in line.lower():
            print(f"  PARTIAL at L{li+1}: {line[:120]}...")
            break
    else:
        # Try first 3 words
        snippet3 = ' '.join(words[:3])
        for li, line in enumerate(content.splitlines()):
            if snippet3.lower() in line.lower():
                print(f"  WEAK PARTIAL at L{li+1}: {line[:120]}...")
                break
        else:
            print(f"  NOT FOUND in output at all")
