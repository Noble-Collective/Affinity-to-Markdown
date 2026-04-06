"""Diagnose why Phase 1 doesn't catch specific standalone callout lines"""
import os, sys, re
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from pathlib import Path
from run import load_template, detect_body_font, build_callout_set, _callout_regex, _normalise_for_callout_match

PDF = os.path.join(os.path.dirname(__file__), "2026-04-03 HomeStead-Interior-Affinity Design-v1.001.pdf")
RAW = os.path.join(os.path.dirname(__file__), "2026-04-03 HomeStead-Interior-Affinity Design-v1.001.raw.md")

cfg = load_template("homestead")
_, bs = detect_body_font(Path(PDF))
ct = build_callout_set(Path(PDF), cfg, bs)

print(f"Callout set: {len(ct)} items")

# Build regexes same as fix_callouts does
normalized = [(c, _normalise_for_callout_match(c)) for c in ct]
regexes = [(c, nc, _callout_regex(c)) for c, nc in normalized]

# Read raw markdown and find lines containing target text
with open(RAW, encoding='utf-8') as f:
    raw_lines = f.readlines()

targets = [
    "Christian homebuilding is a matter of establishing",
    "fear of the Lord establishes a hearty",
    "calling children Godward",
]

for target in targets:
    print(f"\n{'='*60}")
    print(f"TARGET: {target[:50]}")
    for i, line in enumerate(raw_lines):
        if target.lower() in line.lower() and len(line.strip()) < 300:
            s = line.strip()
            print(f"\n  Raw L{i+1} ({len(s)} chars): {s[:120]}...")
            
            # Test Phase 1: does any regex match from start?
            matched_phase1 = False
            for c, nc, rx in regexes:
                m = rx.match(s)
                if m:
                    remainder = s[m.end():].strip().strip('.,;:!?\'"')
                    print(f"    REGEX MATCH from start, remainder: '{remainder}'")
                    if not remainder:
                        print(f"    -> Phase 1 WOULD REMOVE this line")
                        matched_phase1 = True
                    else:
                        print(f"    -> Phase 1 would NOT remove (remainder exists)")
                    break
            
            if not matched_phase1:
                # Try search instead of match to see if the text is there at all
                for c, nc, rx in regexes:
                    m = rx.search(s)
                    if m:
                        print(f"    REGEX SEARCH found at pos {m.start()}-{m.end()} (line len {len(s)})")
                        print(f"    Callout: {c[:80]}...")
                        if m.start() > 0:
                            print(f"    Text BEFORE match: '{s[:m.start()][-30:]}'")
                        break
                else:
                    print(f"    NO regex matches this line at all")
                    # Check if normalised text matches
                    nl = _normalise_for_callout_match(s)
                    for c, nc, rx in regexes:
                        if target.lower()[:30] in nc.lower():
                            print(f"    Callout nc: {nc[:80]}")
                            print(f"    Line nl:    {nl[:80]}")
                            # Show first difference
                            for j in range(min(len(nl), len(nc))):
                                if j < len(nl) and j < len(nc) and nl[j] != nc[j]:
                                    print(f"    DIFF at pos {j}: line='{nl[j]}' (U+{ord(nl[j]):04X}) vs callout='{nc[j]}' (U+{ord(nc[j]):04X})")
                                    print(f"    Context: ...{nl[max(0,j-10):j+10]}... vs ...{nc[max(0,j-10):j+10]}...")
                                    break
                            break
