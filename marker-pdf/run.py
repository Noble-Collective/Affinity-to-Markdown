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
    - Remove image reference lines  ![](...) 
    - Strip CRLF line endings
    - Collapse 3+ blank lines to 2
    """
    lines = markdown.replace('\r\n', '\n').replace('\r', '\n').splitlines()
    out = []
    blank_count = 0
    for line in lines:
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

    print("Loading models (~30s from disk)...")
    import torch
    from marker.models import create_model_dict
    models = create_model_dict(device="cpu", dtype=torch.float32)
    print("Models loaded.")

    # ── Marker configuration — iteration 3b ──────────────────────────────
    #
    # Note: block_relabel_str removed — Marker bug where some blocks have
    # top_k=None, causing TypeError: '>' not supported between NoneType and float.
    # Filed as known Marker issue. Will revisit when fixed upstream.
    #
    # Other changes vs iteration 2:
    # - level_count: 3 (fewer KMeans clusters = simpler heading assignment)
    # - merge_threshold: 0.4 (merge closer heading sizes together)
    # - BlockquoteProcessor tolerances loosened (min_x_indent 0.01, tolerances 0.05)
    # - TextProcessor_column_gap_ratio: 0.06 (fix 2-column hyphenation artifacts)
    # - disable_links: True (reduce text span fragmentation from hyperlinks)

    config = {
        # Heading detection
        "level_count": 3,
        "merge_threshold": 0.4,
        "default_level": 3,
        # Running header suppression
        "common_element_threshold": 0.15,
        "text_match_threshold": 85,
        # Blockquote detection — very low indent + loose alignment
        "BlockquoteProcessor_min_x_indent": 0.01,
        "BlockquoteProcessor_x_start_tolerance": 0.05,
        "BlockquoteProcessor_x_end_tolerance": 0.05,
        # Multi-column text joining (fixes hyphenation artifacts)
        "TextProcessor_column_gap_ratio": 0.06,
        # Strip link annotations
        "disable_links": True,
        # Performance
        "disable_ocr": True,
        "pdftext_workers": 1,
        "DocumentBuilder_lowres_image_dpi": 72,
        # Suppress image output
        "disable_image_extraction": True,
        "extract_images": False,
    }

    # Note: BlockRelabelProcessor kept in list but block_relabel_str is empty
    # so it runs as a no-op. Removing it entirely also works.
    processor_list = [
        "marker.processors.order.OrderProcessor",
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
