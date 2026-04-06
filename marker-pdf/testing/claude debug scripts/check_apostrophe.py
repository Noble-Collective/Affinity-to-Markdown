"""Check exact character encoding around God's in the output"""
import re, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from run import _callout_regex, _normalise_for_callout_match, load_template, detect_body_font, build_callout_set
from pathlib import Path

BASE = os.path.dirname(__file__)
path = os.path.join(BASE, "2026-04-03 HomeStead-Interior-Affinity Design-v1.001.raw_processed.md")
PDF = os.path.join(BASE, "2026-04-03 HomeStead-Interior-Affinity Design-v1.001.pdf")

with open(path, encoding='utf-8') as f:
    lines = f.readlines()

# Find "For all believers" line and show exact bytes
for i, line in enumerate(lines):
    if 'For all believers' in line and len(line.strip()) < 100:
        s = line.strip()
        # Show the apostrophe in "God's"
        idx = s.find("God")
        if idx >= 0:
            snippet = s[idx:idx+6]
            print(f"Line {i+1}: {repr(snippet)}")
            for c in snippet:
                print(f"  '{c}' = U+{ord(c):04X}")
        
        # Show full line repr
        print(f"Full: {repr(s[:80])}")
        
        # Now test: build the callout regex and try matching against joined text
        # Simulate what Phase 2 would do
        group = []
        # Scan backward to find group start
        j = i
        while j >= 0 and (not lines[j].strip() or (lines[j].strip() and not any(lines[j].startswith(p) for p in ('#', '>', '<<', '-', '|', '![')))):
            if lines[j].strip():
                group.insert(0, lines[j].strip())
            j -= 1
        # Scan forward
        j = i + 1
        while j < len(lines):
            if not lines[j].strip():
                if j+1 < len(lines) and lines[j+1].strip() and not any(lines[j+1].startswith(p) for p in ('#', '>', '<<', '-', '|', '![')):
                    group.append(lines[j+1].strip())
                    j += 2; continue
                break
            elif any(lines[j].startswith(p) for p in ('#', '>', '<<', '-', '|', '![')): break
            else: group.append(lines[j].strip()); j += 1
        
        joined = ' '.join(group)
        print(f"\nSimulated group: {len(group)} lines, {len(joined)} chars")
        
        # Get the specific callout
        cfg = load_template("homestead")
        bfn, bs = detect_body_font(Path(PDF))
        ct = build_callout_set(Path(PDF), cfg, bs)
        for c in ct:
            if 'believers' in c and 'devoted' in c:
                rx = _callout_regex(c)
                m = rx.search(joined)
                print(f"\nCallout: {c[:80]}")
                print(f"Regex match on joined: {bool(m)}")
                if not m:
                    # Find where it diverges
                    # Check apostrophe in callout text
                    cidx = c.find("God")
                    if cidx >= 0:
                        csnippet = c[cidx:cidx+6]
                        print(f"Callout God's: {repr(csnippet)}")
                        for ch in csnippet:
                            print(f"  '{ch}' = U+{ord(ch):04X}")
                    
                    # Check if the specific sentence boundary matches
                    if "people." in joined:
                        pidx = joined.index("people.")
                        boundary = joined[pidx:pidx+20]
                        print(f"\nBoundary in joined: {repr(boundary)}")
                break
        break
