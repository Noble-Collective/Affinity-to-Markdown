#!/usr/bin/env python
"""
run.py - Simple local runner for PDF to Markdown conversion.

Usage:
  python run.py path/to/book.pdf
  python run.py path/to/book.pdf --page-range 62-200
  python run.py path/to/book.pdf output.md --page-range 62-200
"""
import sys
import argparse
import logging
from pathlib import Path

# Suppress noisy torch/transformers warnings
logging.basicConfig(level=logging.WARNING)

def main():
    parser = argparse.ArgumentParser(description="Convert PDF to Markdown using Marker.")
    parser.add_argument("input", help="Path to the PDF file")
    parser.add_argument("output", nargs="?", help="Output .md path (optional)")
    parser.add_argument("--page-range", default="", help="e.g. '62-200' (0-indexed)")
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
    print("Loading models (first run downloads ~3 GB, takes 5-10 min)...")
    print("Subsequent runs load from disk in ~30 seconds.")
    import torch
    from marker.models import create_model_dict
    models = create_model_dict(device="cpu", dtype=torch.float32)
    print("Models loaded.")

    # Convert
    from marker.converters.pdf import PdfConverter
    config = {
        "level_count": 6,
        "default_level": 3,
        "common_element_threshold": 0.15,
        "text_match_threshold": 85,
        "disable_ocr": True,
        "pdftext_workers": 1,
        "DocumentBuilder_lowres_image_dpi": 72,
        "disable_image_extraction": True,
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

    print(f"Converting {pdf_path.name}...")
    converter = PdfConverter(
        artifact_dict=models,
        processor_list=processor_list,
        config=config,
    )
    rendered = converter(str(pdf_path))

    output_path.write_text(rendered.markdown, encoding="utf-8")
    lines = len(rendered.markdown.splitlines())
    print(f"Done! Written to: {output_path} ({lines} lines)")

if __name__ == "__main__":
    main()
