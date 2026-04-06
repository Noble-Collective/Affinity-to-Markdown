"""
Diagnostic: examine sign-off text blocks ("July 2024", "March 2026") to understand
why they're blockquoted instead of cited, and whether PyMuPDF sees them as multi-line.
Run: venv311/Scripts/python testing/check_fonts.py
"""
import fitz, sys, os, re

PDF = os.path.join(os.path.dirname(__file__), "2026-04-03 HomeStead-Interior-Affinity Design-v1.001.pdf")
BODY_SIZE = 10.0

doc = fitz.open(PDF)

SEARCH_TERMS = ["july 2024", "march 2026"]

for pi in range(min(30, doc.page_count)):
    page = doc[pi]
    page_text = page.get_text("text").lower()
    matching = [t for t in SEARCH_TERMS if t in page_text]
    if not matching:
        continue

    print(f"\n{'='*70}")
    print(f"Page {pi+1} (index {pi}) — contains: {matching}")
    print(f"{'='*70}")

    for bi, block in enumerate(page.get_text("dict", sort=True)["blocks"]):
        if block.get("type") != 0:
            continue
        full_text = ""
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                full_text += span["text"]
        full_lower = full_text.lower()
        if not any(t in full_lower for t in matching):
            continue

        # This block contains our text — show full details
        fc = {}
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                t = span["text"]
                if t.strip():
                    k = (span["font"], round(span["size"]*2)/2)
                    fc[k] = fc.get(k, 0) + len(t.strip())
        dom_font, dom_size = max(fc, key=fc.get) if fc else ("?", 0)
        dom_ratio = dom_size / BODY_SIZE
        norm_text = " ".join(full_text.split()).strip()

        print(f"\n  Block {bi}:")
        print(f"    Dominant font: {dom_font} {dom_size}pt ratio={dom_ratio:.2f}")
        print(f"    Full text (normalized): '{norm_text}'")
        print(f"    Text length: {len(norm_text)} chars")
        print(f"    Would be: {'bq_set (>80)' if len(norm_text) > 80 else 'cit_set (<=80)'}")
        print(f"    Number of lines in block: {len(block.get('lines', []))}")

        for li, line in enumerate(block.get("lines", [])):
            line_text = "".join(s["text"] for s in line.get("spans", [])).strip()
            spans = [(s["font"], round(s["size"]*2)/2, s["text"].strip()) for s in line.get("spans", []) if s["text"].strip()]
            print(f"    Line {li}: '{line_text}'")
            for font, size, sample in spans:
                print(f"      {font} {size}pt ratio={size/BODY_SIZE:.2f} text='{sample}'")

print("\n--- Why fix_blockquotes skips these ---")
print("Lines starting with '>' are passed through unchanged by fix_blockquotes.")
print("Even if the content is in cit_set, the '>' prefix from Marker prevents correction.")
