#!/usr/bin/env python
"""
run.py - Local runner for PDF to Markdown conversion using Marker.

Usage:
  python run.py path/to/book.pdf
  python run.py path/to/book.pdf --page-range 62-200
  python run.py path/to/book.pdf output.md --page-range 62-200
"""
import sys
import re
import argparse
import logging
from pathlib import Path

logging.basicConfig(level=logging.WARNING)


def post_process(markdown: str) -> str:
    """
    Thin post-processing on Marker's output:
    - Remove image references  ![](...) lines
    - Strip CRLF → LF
    - Collapse 3+ blank lines to 2
    """
    lines = markdown.replace('\r\n', '\n').replace('\r', '\n').splitlines()
    out = []
    blank_count = 0
    for line in lines:
        # Drop image lines
        if re.match(r'^!\[.*?\]\(.*?\)\s*$', line):
            continue
        if line.strip() == '':
            blank_count += 1
            if blank_count <= 2:
                out.append('')
        else:
            blank_count = 0
            out.append(line)
    return '\n'.join(out).strip() + '\n'


def main():
    parser = argparse.ArgumentParser(description="Convert PDF to Markdown using Marker.")
    parser.add_argument("input", help="Path to the PDF file")
    parser.add_argument("output", nargs="?", help="Output .md path (optional)")
    parser.add_argument(
        "--page-range", default="",
        help="0-indexed page range e.g. '62-200' or '0-10,20-30'"
    )
    args = parser.parse_args()

    pdf_path = Path(args.input)
    if not pdf_path.exists():
        print(f"ERROR: File not found: {pdf_path}")
        sys.exit(1)

    output_path = Path(args.output) if args.output else pdf_path.with_suffix(".md")

    # Parse page range
    page_range = None
    if args.page_range.strip():
        pages = []
        for part in args.page_range.split(","):
            part = part.strip()
            if "-" in part:
                start, end = part.split("-", 1)
                pages.extend(range(int(start), int(end) + 1))
            else:
                pages.append(int(part))
        page_range = pages
        print(f"Page range: {page_range[0]}-{page_range[-1]} ({len(page_range)} pages)")

    # Load models
    print("Loading models (first run ~30s from disk)...")
    import torch
    from marker.models import create_model_dict
    models = create_model_dict(device="cpu", dtype=torch.float32)
    print("Models loaded.")

    # ── Marker configuration ──────────────────────────────────────────────
    # level_count=4: KMeans finds 4 heading clusters across the document.
    #   Using 6 over-splits and promotes everything to H1.
    #   4 correctly finds: session title, movement titles,
    #   section headings, sub-section headings.
    #
    # default_level=3: unclustered headers default to H3 (###)
    #
    # common_element_threshold=0.15: suppress running headers appearing
    #   on 15%+ of pages (e.g. "INTRODUCTION SESSION ONE" drop-caps)
    #
    # BlockquoteProcessor_min_x_indent=0.03: lower indentation threshold
    #   to catch the 8pt scripture quotes which have modest indentation
    #
    # extract_images=False + disable_image_extraction=True:
    #   belt-and-suspenders to suppress ![]() image references in output
    config = {
        # Heading detection
        "level_count": 4,
        "default_level": 3,
        # Running header suppression
        "common_element_threshold": 0.15,
        "text_match_threshold": 85,
        # Blockquote detection — lower indent threshold
        "BlockquoteProcessor_min_x_indent": 0.03,
        # Performance
        "disable_ocr": True,
        "pdftext_workers": 1,
        "DocumentBuilder_lowres_image_dpi": 72,
        # Suppress image output
        "disable_image_extraction": True,
        "extract_images": False,
    }

    processor_list = [
        "marker.processors.order.OrderProcessor",
        "marker.processors.block_relabel.BlockRelabelProcessor",
        "marker.processors.line_merge.LineMergeProcessor",
        "marker.processors.blockquote.BlockquoteProcessor",
        "marker.processors.ignoretext.IgnoreTextProcessor",
        "marker.processors.list.ListProcessor",
        "marker.processors.page_header.PageHeaderProcessor",
        "marker.processors.sectionheader.SectionHeaderProcessor",
        "marker.processors.text.TextProcessor",
        "marker.processors.blank_page.BlankPageProcessor",
    ]

    if page_range:
        config["page_range"] = page_range

    from marker.converters.pdf import PdfConverter
    print(f"Converting {pdf_path.name}...")
    converter = PdfConverter(
        artifact_dict=models,
        processor_list=processor_list,
        config=config,
    )
    rendered = converter(str(pdf_path))

    markdown = post_process(rendered.markdown)
    output_path.write_text(markdown, encoding="utf-8")
    lines = len(markdown.splitlines())
    print(f"Done! Written to: {output_path} ({lines} lines)")


if __name__ == "__main__":
    main()
