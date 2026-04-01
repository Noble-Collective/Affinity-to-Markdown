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


def patch_block_relabel():
    """
    Patch a bug in Marker's BlockRelabelProcessor where block.top_k.get()
    returns None for some blocks, causing:
      TypeError: '>' not supported between instances of 'NoneType' and 'float'

    The fix: skip relabeling when confidence is None (block has no confidence score).
    This is a one-line fix to the Marker source — applied as a monkey-patch so
    we don't need to modify files in the venv.
    """
    from copy import deepcopy
    from marker.processors.block_relabel import BlockRelabelProcessor
    from marker.schema.registry import get_block_class
    from marker.schema.blocks import BlockId
    from marker.logger import get_logger
    logger = get_logger()

    def patched_call(self, document):
        if len(self.block_relabel_map) == 0:
            return
        for page in document.pages:
            for block in page.structure_blocks(document):
                if block.block_type not in self.block_relabel_map:
                    continue
                block_id = BlockId(
                    page_id=page.page_id,
                    block_id=block.block_id,
                    block_type=block.block_type,
                )
                confidence_thresh, relabel_block_type = self.block_relabel_map[block.block_type]
                confidence = block.top_k.get(block.block_type)
                # BUG FIX: skip blocks with no confidence score (top_k returns None)
                if confidence is None:
                    continue
                if confidence > confidence_thresh:
                    logger.debug(
                        f"Skipping relabel for {block_id}; "
                        f"Confidence: {confidence} > {confidence_thresh}"
                    )
                    continue
                new_block_cls = get_block_class(relabel_block_type)
                new_block = new_block_cls(
                    polygon=deepcopy(block.polygon),
                    page_id=block.page_id,
                    structure=deepcopy(block.structure),
                    text_extraction_method=block.text_extraction_method,
                    source="heuristics",
                    top_k=block.top_k,
                    metadata=block.metadata,
                )
                page.replace_block(block, new_block)
                logger.debug(f"Relabelled {block_id} to {relabel_block_type}")

    BlockRelabelProcessor.__call__ = patched_call


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

    # Apply bug fix to Marker before loading models
    patch_block_relabel()

    print("Loading models (~30s from disk)...")
    import torch
    from marker.models import create_model_dict
    models = create_model_dict(device="cpu", dtype=torch.float32)
    print("Models loaded.")

    # ── Marker configuration — iteration 3 (with block_relabel restored) ─
    config = {
        # Heading detection
        "level_count": 3,
        "merge_threshold": 0.4,
        "default_level": 3,
        # Demote low-confidence SectionHeader blocks to Text before KMeans.
        # Restored now that the top_k=None bug is patched.
        "block_relabel_str": "SectionHeader:Text:0.6",
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
