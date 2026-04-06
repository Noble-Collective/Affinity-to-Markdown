"""
Investigate A5 and B3 audit findings.
Run: venv311/Scripts/python testing/investigate_a5_b3.py
"""
import re, os

BASE = os.path.join(os.path.dirname(__file__))
RAW = os.path.join(BASE, "2026-04-03 HomeStead-Interior-Affinity Design-v1.001.raw.md")

# Find the latest output file
mds = sorted([f for f in os.listdir(BASE) if f.endswith('.md') and not f.endswith('.raw.md')],
             key=lambda f: os.path.getmtime(os.path.join(BASE, f)))
OUT = os.path.join(BASE, mds[-1]) if mds else None

with open(RAW, encoding='utf-8') as f:
    raw_lines = f.readlines()

out_lines = []
if OUT:
    with open(OUT, encoding='utf-8') as f:
        out_lines = f.readlines()
    print(f"Output file: {os.path.basename(OUT)}\n")

print("=" * 70)
print("A5: Lines matching r'^\\*\".+\\.\\.\\.\\*$' (italic truncated quotes)")
print("=" * 70)

pat_a5 = re.compile(r'^\*".+\.\.\.\*$')

print("\nIn RAW markdown:")
count = 0
for i, line in enumerate(raw_lines):
    if pat_a5.match(line.strip()):
        print(f"  Line {i+1}: {line.rstrip()}")
        count += 1
if count == 0: print("  (none)")

print(f"\nIn OUTPUT markdown:")
count = 0
for i, line in enumerate(out_lines):
    if pat_a5.match(line.strip()):
        print(f"  Line {i+1}: {line.rstrip()}")
        count += 1
if count == 0: print("  (none - all removed by fix_structural_labels)")

# Broader check: anything starting with *" 
print(f"\nBroader: RAW lines starting with *\" (italic-opening quote):")
count = 0
for i, line in enumerate(raw_lines):
    s = line.strip()
    if s.startswith('*"') and len(s) > 10:
        print(f"  Line {i+1}: {s[:100]}")
        count += 1
if count == 0: print("  (none)")

print("\n" + "=" * 70)
print("B3: Lines matching r'^#{1,6}\\s+\\w.*:$' (heading ending with colon)")
print("=" * 70)

pat_b3 = re.compile(r'^#{1,6}\s+\w.*:$')

print("\nIn RAW markdown:")
count = 0
for i, line in enumerate(raw_lines):
    if pat_b3.match(line.strip()):
        print(f"  Line {i+1}: {line.rstrip()}")
        count += 1
if count == 0: print("  (none)")

print(f"\nHeading-ending-colon in OUTPUT (should be 0 after B3 strips prefix):")
count = 0
for i, line in enumerate(out_lines):
    if pat_b3.match(line.strip()):
        print(f"  Line {i+1}: {line.rstrip()}")
        count += 1
if count == 0: print("  (none - all converted by fix_structural_labels)")

# What did B3 produce? Look for standalone colon-ending lines that look like sub-labels
print(f"\nStandalone lines ending with ':' in OUTPUT (B3 results):")
count = 0
for i, line in enumerate(out_lines):
    s = line.strip()
    if not s or s.startswith('#') or s.startswith('>') or s.startswith('-') or s.startswith('*') or s.startswith('<') or s.startswith('|') or s.startswith('!'):
        continue
    if s.endswith(':') and 5 < len(s) < 80:
        # Check context
        prev = out_lines[i-1].strip() if i > 0 else ""
        nxt = out_lines[i+1].strip() if i+1 < len(out_lines) else ""
        print(f"  Line {i+1}: {s}")
        count += 1
if count == 0: print("  (none)")
print(f"\n  Total: {count}")
