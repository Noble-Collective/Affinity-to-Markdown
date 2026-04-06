"""Show context around # PART headings in output"""
import os

BASE = os.path.join(os.path.dirname(__file__))
mds = sorted([f for f in os.listdir(BASE) if f.endswith('.md') and not f.endswith('.raw.md')],
             key=lambda f: os.path.getmtime(os.path.join(BASE, f)))
OUT = os.path.join(BASE, mds[-1])
print(f"File: {os.path.basename(OUT)}\n")

with open(OUT, encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if line.strip().startswith('# PART '):
        start = max(0, i - 8)
        end = min(len(lines), i + 8)
        print(f"{'='*70}")
        print(f"PART heading at line {i+1}")
        print(f"{'='*70}")
        for j in range(start, end):
            marker = ">>>" if j == i else "   "
            print(f"{marker} {j+1:4d}: {lines[j].rstrip()}")
        print()
