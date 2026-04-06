"""Show context around **Verse** lines in output"""
import os

BASE = os.path.join(os.path.dirname(__file__))
mds = sorted([f for f in os.listdir(BASE) if f.endswith('.md') and not f.endswith('.raw.md')],
             key=lambda f: os.path.getmtime(os.path.join(BASE, f)))
OUT = os.path.join(BASE, mds[-1])

with open(OUT, encoding='utf-8') as f:
    lines = f.readlines()

count = 0
for i, line in enumerate(lines):
    if line.strip().startswith('**Verse ') and line.strip().endswith('**'):
        count += 1
        if count <= 3:  # show first 3 examples
            start = max(0, i - 1)
            end = min(len(lines), i + 5)
            print(f"--- Line {i+1} ---")
            for j in range(start, end):
                print(f"  {j+1:4d}: {repr(lines[j].rstrip())}")
            print()

print(f"Total **Verse N** lines: {count}")
