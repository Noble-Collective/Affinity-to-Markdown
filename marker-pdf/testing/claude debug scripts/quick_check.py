"""Quick check on (36) output"""
import re, os
path = os.path.join(os.path.dirname(__file__), "2026-04-03 HomeStead-Interior-Affinity Design-v1.001 (36).md")
with open(path, encoding='utf-8') as f:
    content = f.read()
lines = content.splitlines()

tags = re.findall(r'<Callout>', content)
print(f"Total <Callout> tags: {len(tags)}")

# Check "For all believers"
for i, line in enumerate(lines):
    if 'For all believers' in line:
        joined = 'One cannot exist' in line
        print(f"\nLine {i+1} ({len(line)} chars): joined={'YES' if joined else 'NO'}")
        print(f"  {line[:150]}...")
        if '<Callout>' in line:
            print("  HAS CALLOUT TAG!")

# Check "Parents are best caretakers"  
for i, line in enumerate(lines):
    if 'Parents are best caretakers' in line:
        print(f"\nLine {i+1}: {line[:120]}")
        if '<Callout>' in line:
            print("  HAS CALLOUT TAG!")

# Count unmatched by importing callout set
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from run import load_template, detect_body_font, build_callout_set, _callout_regex
from pathlib import Path
PDF = os.path.join(os.path.dirname(__file__), "2026-04-03 HomeStead-Interior-Affinity Design-v1.001.pdf")
cfg = load_template("homestead")
_, bs = detect_body_font(Path(PDF))
ct = build_callout_set(Path(PDF), cfg, bs)
unmatched = 0
for c in ct:
    rx = _callout_regex(c)
    if not rx.search(content):
        unmatched += 1
        print(f"\nUNMATCHED: {c[:80]}...")
print(f"\n=== SUMMARY: {len(tags)} tags, {unmatched} unmatched of {len(ct)} callouts ===")
