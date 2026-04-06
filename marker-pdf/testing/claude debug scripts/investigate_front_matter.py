"""
Diagnostic: examine front matter pages (1-8) from PyMuPDF perspective.
For C1 (line splitting) and C2 (copyright prefix stripping).

Run: venv311/Scripts/python testing/investigate_front_matter.py
"""
import fitz, os, re

PDF = os.path.join(os.path.dirname(__file__), "2026-04-03 HomeStead-Interior-Affinity Design-v1.001.pdf")
BODY_SIZE = 10.0

doc = fitz.open(PDF)

def size_bucket(s): return round(float(s) * 2) / 2

def font_weight(f):
    n = f.lower()
    if "bold" in n and "italic" in n: return "bold-italic"
    if "bold" in n: return "bold"
    if "italic" in n: return "italic"
    return "regular"

print("=" * 80)
print("FRONT MATTER PAGES: PyMuPDF block analysis")
print("Looking for: multi-line blocks (C1) and small-font non-quote text (C2)")
print("=" * 80)

for pi in range(min(10, doc.page_count)):
    page = doc[pi]
    pw = page.rect.width
    blocks = page.get_text("dict", sort=True)["blocks"]
    text_blocks = [b for b in blocks if b.get("type") == 0]
    
    if not text_blocks:
        continue
    
    print(f"\n{'─' * 80}")
    print(f"PAGE {pi+1} (index {pi})  |  {len(text_blocks)} text blocks")
    print(f"{'─' * 80}")
    
    for bi, block in enumerate(text_blocks):
        # Collect font info
        fc = {}
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                t = span["text"]
                if t.strip():
                    k = (span["font"], size_bucket(span["size"]))
                    fc[k] = fc.get(k, 0) + len(t.strip())
        if not fc:
            continue
        
        dom_font, dom_size = max(fc, key=fc.get)
        ratio = dom_size / BODY_SIZE
        weight = font_weight(dom_font)
        
        # Collect lines
        block_lines = []
        for line in block.get("lines", []):
            lt = "".join(s["text"] for s in line.get("spans", [])).strip()
            if lt:
                block_lines.append(lt)
        
        if not block_lines:
            continue
        
        full_text = " ".join(block_lines)
        num_lines = len(block_lines)
        bbox = block["bbox"]  # (x0, y0, x1, y1)
        x_pct = bbox[0] / pw * 100  # left edge as % of page width
        
        # Flags
        is_small = ratio < 0.95  # smaller than body
        is_multiline = num_lines > 1
        is_right = x_pct > 50
        is_short = len(full_text) < 80
        
        # Tags for what's interesting
        tags = []
        if is_multiline: tags.append("MULTI-LINE")
        if is_small: tags.append(f"SMALL({ratio:.2f})")
        if is_right: tags.append(f"RIGHT({x_pct:.0f}%)")
        if is_short and not is_small: tags.append("SHORT-BODY")
        
        tag_str = f"  [{', '.join(tags)}]" if tags else ""
        
        print(f"\n  Block {bi}: {weight} {dom_size}pt ratio={ratio:.2f} x={x_pct:.0f}%{tag_str}")
        print(f"    Full: {full_text[:90]}{'...' if len(full_text) > 90 else ''}")
        
        if is_multiline:
            print(f"    Lines ({num_lines}):")
            for li, lt in enumerate(block_lines):
                print(f"      [{li}] {lt}")
        
        # Show all font variants if mixed
        if len(fc) > 1:
            print(f"    Mixed fonts:")
            for (f, s), c in sorted(fc.items(), key=lambda x: -x[1]):
                print(f"      {font_weight(f)} {s}pt ({c} chars)")

print("\n\n" + "=" * 80)
print("ANALYSIS SUMMARY")
print("=" * 80)

print("\nC1 (line splitting): Multi-line blocks that Marker joins into one line.")
print("   If PyMuPDF preserves the line breaks, we can build a map to restore them.")
print("   Key question: do ALL multi-line blocks in front matter need line restoration,")
print("   or only specific ones? Need to check what Marker does with each.")

print("\nC2 (copyright prefix): Small-font blocks on copyright page that are NOT quotes.")
print("   If we can identify the copyright page by position or content pattern,")
print("   we can exclude its blocks from bq_set/cit_set entirely.")
print("   Key question: what distinguishes copyright boilerplate from actual blockquotes?")
print("   Both are at 8pt. Copyright text is on specific pages (typically 4-6).")
