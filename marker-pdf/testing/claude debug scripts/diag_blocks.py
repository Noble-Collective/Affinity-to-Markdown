"""Dump PDF blocks around truncated callouts to see font properties"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from pathlib import Path
from run import load_template, detect_body_font, size_bucket, font_weight, _match_rule

PDF = os.path.join(os.path.dirname(__file__), "2026-04-03 HomeStead-Interior-Affinity Design-v1.001.pdf")
cfg = load_template("homestead")
_, bs = detect_body_font(Path(PDF))
sig = cfg.get("callout_signature", [])

import fitz
doc = fitz.open(PDF)

# Search for pages containing our target callout texts
targets = ["Christian homebuilding is a matter", "What a wonderful and demanding"]

for target in targets:
    print(f"\n{'='*70}")
    print(f"SEARCHING: {target}")
    for pi in range(doc.page_count):
        page_text = doc[pi].get_text()
        if target.lower() not in page_text.lower():
            continue
        print(f"\n  Page {pi+1}:")
        blocks = doc[pi].get_text("dict", sort=True)["blocks"]
        for bi, block in enumerate(blocks):
            if block.get("type") != 0: continue
            text = ""
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text += span["text"]
            text_clean = " ".join(text.split()).strip()
            if not text_clean: continue
            # Show blocks near our target
            if target.lower() in text_clean.lower() or (bi > 0 and target.lower() in " ".join(text.split()).lower()):
                # Show this block and neighbors
                for offset in range(-2, 3):
                    idx = bi + offset
                    if idx < 0 or idx >= len(blocks) or blocks[idx].get("type") != 0:
                        continue
                    b = blocks[idx]
                    bt = ""
                    fonts = []
                    for line in b.get("lines", []):
                        for span in line.get("spans", []):
                            bt += span["text"]
                            t = span["text"].strip()
                            if t:
                                w = font_weight(span["font"])
                                r = round(size_bucket(span["size"]) / bs, 2)
                                matches_sig = any(_match_rule(w, r, rule) for rule in sig)
                                fonts.append(f"{w}@{r}{'*' if matches_sig else ''}")
                    bt = " ".join(bt.split()).strip()
                    marker = ">>>" if idx == bi else "   "
                    is_match = all(any(_match_rule(font_weight(span["font"]), size_bucket(span["size"])/bs, rule) for rule in sig) 
                                  for line in b.get("lines",[]) for span in line.get("spans",[]) if span["text"].strip())
                    print(f"    {marker} Block {idx}: is_callout={is_match} fonts={set(fonts)}")
                    print(f"        {bt[:100]}")
                break  # only first matching page
