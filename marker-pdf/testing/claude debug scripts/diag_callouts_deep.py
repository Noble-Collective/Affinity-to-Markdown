"""Deep dive: trace each unmatched callout to find exact mismatch"""
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

cfg = load_template("homestead")
bfn, bs = detect_body_font(Path(PDF))
ct = build_callout_set(Path(PDF), cfg, bs)

with open(OUT, encoding='utf-8') as f:
    output = f.read()
out_lines = output.splitlines()

with open(RAW, encoding='utf-8') as f:
    raw = f.read()

o = []

# For each unmatched callout, trace why
for c in ct:
    nc = _normalise_for_callout_match(c)
    rx = _callout_regex(c)
    if rx.search(output):
        continue  # matched, skip
    
    o.append(f"\n{'='*70}")
    o.append(f"UNMATCHED: {c[:80]}...")
    o.append(f"  Full ({len(c)} chars): {c}")
    o.append(f"  Regex: {rx.pattern[:100]}")
    
    # Find the first 6 words in the output
    words = c.split()[:6]
    snippet = ' '.join(words).lower()
    
    # Search output for the snippet
    found_lines = []
    for i, line in enumerate(out_lines):
        if snippet[:30].lower() in line.lower():
            found_lines.append(i)
    
    if found_lines:
        o.append(f"\n  OUTPUT CONTEXT (first match at line {found_lines[0]+1}):")
        i = found_lines[0]
        for j in range(max(0, i-2), min(len(out_lines), i+5)):
            o.append(f"    {j+1:4d}: {out_lines[j][:120]}")
        
        # Try to simulate Phase 2 grouping from this line
        # Find the group start (scan backward to first blank-before-structural or double-blank)
        start = i
        while start > 0:
            if not out_lines[start-1].strip():
                if start-2 >= 0 and not out_lines[start-2].strip():
                    break  # double blank = group boundary
                if start-2 >= 0 and any(out_lines[start-2].startswith(p) for p in ('#', '>', '<<', '-', '|', '![')):
                    break
                start -= 2  # skip blank, include previous body line
            else:
                start -= 1
        
        # Build group forward from start
        group = []
        j = start
        while j < len(out_lines):
            if out_lines[j].strip() and not any(out_lines[j].startswith(p) for p in ('#', '>', '<<', '-', '|', '![')):
                group.append(out_lines[j].strip())
                j += 1
            elif not out_lines[j].strip():
                if j+1 < len(out_lines) and out_lines[j+1].strip() and not any(out_lines[j+1].startswith(p) for p in ('#', '>', '<<', '-', '|', '![')):
                    j += 1
                    continue
                break
            else:
                break
        
        joined = ' '.join(group)
        o.append(f"\n  SIMULATED GROUP ({len(group)} lines, {len(joined)} chars):")
        o.append(f"    {joined[:200]}...")
        
        # Test regex against joined
        m = rx.search(joined)
        o.append(f"\n  REGEX MATCH ON JOINED: {bool(m)}")
        if not m:
            # Find where it diverges - try matching progressively longer prefixes
            test_words = c.split()
            last_match = 0
            for k in range(1, len(test_words)+1):
                partial = ' '.join(test_words[:k])
                partial_rx = _callout_regex(partial)
                if partial_rx.search(joined):
                    last_match = k
                else:
                    break
            o.append(f"  REGEX MATCHES FIRST {last_match} OF {len(test_words)} WORDS")
            if last_match < len(test_words):
                failing_word = test_words[last_match] if last_match < len(test_words) else "?"
                o.append(f"  FAILS AT WORD: '{failing_word}'")
                # Show what the joined text has at that point
                partial_text = ' '.join(test_words[:last_match])
                idx = joined.lower().find(partial_text.lower())
                if idx >= 0:
                    context = joined[idx:idx+len(partial_text)+30]
                    o.append(f"  JOINED TEXT AT FAILURE: ...{context}...")
                    # Show char-by-char comparison
                    expected = c[len(partial_text):len(partial_text)+20]
                    actual = joined[idx+len(partial_text):idx+len(partial_text)+20]
                    o.append(f"  EXPECTED NEXT: {repr(expected)}")
                    o.append(f"  ACTUAL NEXT:   {repr(actual)}")
    else:
        o.append(f"\n  TEXT NOT FOUND IN OUTPUT AT ALL")
        # Check raw
        raw_found = []
        for i, line in enumerate(raw.splitlines()):
            if snippet[:30].lower() in line.lower():
                raw_found.append((i, line[:100]))
        if raw_found:
            o.append(f"  But found in RAW at lines: {[r[0]+1 for r in raw_found]}")
            for li, lt in raw_found[:3]:
                o.append(f"    {li+1}: {lt}")
        else:
            o.append(f"  Also NOT in raw markdown")

outpath = os.path.join(BASE, "diag_callouts_deep.txt")
with open(outpath, "w", encoding="utf-8") as f:
    f.write('\n'.join(o))
print(f"Written to {outpath}")
