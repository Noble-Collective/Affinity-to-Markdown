"""
Extract all PyMuPDF-derived data from the PDF into a JSON file.
Run once, then upload the JSON + raw.md so Claude can iterate
the postprocessing pipeline without needing PyMuPDF or the PDF.

Usage:
  python extract_pdf_data.py <pdf_path> [--template homestead]
"""
import os, sys, json, argparse
# Ensure marker-pdf dir is on path regardless of where script is run from
_script_dir = os.path.dirname(os.path.abspath(__file__))
_marker_dir = os.path.dirname(os.path.dirname(_script_dir))
sys.path.insert(0, _marker_dir)
from pathlib import Path
from run import (
    load_template, detect_body_font, build_heading_map, build_skip_set,
    build_blockquote_set, build_verse_map, build_callout_set,
    build_inline_bold_set, build_rotated_subdivisions,
    build_right_aligned_citations, build_verse_superscript_set,
)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--template", default="homestead")
    ap.add_argument("--page-range", default="")
    args = ap.parse_args()

    pp = Path(args.pdf)
    cfg = load_template(args.template)

    page_range = None
    if args.page_range.strip():
        pages = []
        for part in args.page_range.split(","):
            part = part.strip()
            if "-" in part:
                s, e = part.split("-", 1)
                pages.extend(range(int(s), int(e) + 1))
            else:
                pages.append(int(part))
        page_range = pages

    print(f"PDF: {pp}")
    print(f"Template: {args.template}")

    bfn, bs = detect_body_font(pp, page_range)
    print(f"Body font: {bfn} @ {bs}pt")

    print("Building heading map...")
    hm, ho = build_heading_map(pp, cfg, bs, page_range)

    print("Building skip set...")
    ss = build_skip_set(pp, cfg, bs, page_range)

    print("Building blockquote/citation sets...")
    bq, ci = build_blockquote_set(pp, cfg, bs, page_range)

    print("Building verse map...")
    vm = build_verse_map(pp, cfg, bs, page_range)

    print("Building callout set...")
    ct = build_callout_set(pp, cfg, bs, page_range)

    print("Building inline bold set...")
    ib = build_inline_bold_set(pp, cfg, bs, page_range)

    print("Building rotated subdivisions...")
    rs = build_rotated_subdivisions(pp, cfg, bs, page_range)

    print("Building right-aligned citations...")
    ra = build_right_aligned_citations(pp, cfg, bs, page_range)

    print("Building verse superscript set...")
    vs = build_verse_superscript_set(pp, cfg, bs, page_range)

    data = {
        "body_font_name": bfn,
        "body_font_size": bs,
        "template": args.template,
        "heading_map": {k: v for k, v in hm.items()},  # str keys
        "heading_order": ho,  # list of (text, level)
        "skip_set": sorted(ss),
        "blockquote_set": sorted(bq),
        "citation_set": sorted(ci),
        "verse_map": vm,
        "callout_texts": ct,
        "inline_bold": ib,
        "rotated_subdivisions": rs,  # list of (label, anchor_key, page)
        "right_aligned_map": {k: v for k, v in ra.items()},
        "verse_superscripts": sorted(vs),
    }

    out_path = pp.with_suffix(".pdf_data.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\nSaved: {out_path}")
    print(f"  {len(hm)} headings, {len(ho)} ordered, {len(ss)} skips")
    print(f"  {len(bq)} blockquotes, {len(ci)} citations, {len(vm)} verses")
    print(f"  {len(ct)} callouts, {len(ib)} inline bold, {len(vs)} verse sups")
    print(f"  {len(rs)} rotated subdivisions, {len(ra)} right-aligned citations")
    print(f"\nUpload this JSON + the raw.md file to Claude for offline iteration.")

if __name__ == "__main__":
    main()
