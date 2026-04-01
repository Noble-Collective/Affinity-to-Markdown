"""
converter.py — Marker PDF → Markdown conversion logic.

Pure conversion module — no HTTP or web code here.
Can be used as a CLI tool directly:

  python converter.py book.pdf
  python converter.py book.pdf --page-range 62-200
  python converter.py book.pdf output.md
"""
import logging
import sys
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Trimmed processor list ────────────────────────────────────────────────────
PROCESSOR_LIST = [
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

# ── Marker configuration ──────────────────────────────────────────────────────
MARKER_CONFIG: dict = {
    "level_count": 6,
    "default_level": 3,
    "common_element_threshold": 0.15,
    "text_match_threshold": 85,
    "disable_ocr": True,
    "pdftext_workers": 1,
    "DocumentBuilder_lowres_image_dpi": 72,
    "disable_image_extraction": True,
}


def parse_page_range(s: str) -> list[int]:
    """
    Parse a page range string into 0-indexed page numbers.
      "62-200"     → list(range(62, 201))
      "0-10,20-30" → mixed ranges
    """
    pages: list[int] = []
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = part.split("-", 1)
            pages.extend(range(int(start), int(end) + 1))
        else:
            pages.append(int(part))
    return pages


def convert_pdf(
    pdf_path: Path,
    page_range: Optional[list[int]] = None,
    models: Optional[dict] = None,
) -> str:
    """
    Convert a PDF file to Markdown using Marker.

    Args:
        pdf_path:   Path to the input PDF.
        page_range: Optional 0-indexed page numbers to convert.
                    Example: list(range(62, 200)) skips front matter.
        models:     Pre-loaded model dict. If None, loads via model_loader.

    Returns:
        Markdown string.
    """
    from marker.converters.pdf import PdfConverter

    if models is None:
        import model_loader
        models = model_loader.get_models()

    config = dict(MARKER_CONFIG)
    if page_range is not None:
        config["page_range"] = page_range

    converter = PdfConverter(
        artifact_dict=models,
        processor_list=PROCESSOR_LIST,
        config=config,
    )

    size_kb = pdf_path.stat().st_size // 1024
    pages_info = f", pages {page_range[0]}–{page_range[-1]}" if page_range else ""
    print(f"  Converting {pdf_path.name} ({size_kb} KB{pages_info})")

    rendered = converter(str(pdf_path))

    lines = len(rendered.markdown.splitlines())
    chars = len(rendered.markdown)
    print(f"  Done: {chars:,} chars, {lines} lines")
    return rendered.markdown


# ── CLI entry point ───────────────────────────────────────────────────────────

def main():
    import argparse
    import torch
    from marker.models import create_model_dict

    parser = argparse.ArgumentParser(
        description="Convert a PDF to Markdown using Marker."
    )
    parser.add_argument("input", help="Path to the input PDF file")
    parser.add_argument(
        "output", nargs="?", help="Output .md path (default: same name as input)"
    )
    parser.add_argument(
        "--page-range",
        default="",
        help="Page range to convert, 0-indexed. e.g. '62-200' or '0-10,20-30'. "
             "Useful for skipping front matter in long documents.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)  # suppress Marker/torch noise

    pdf_path = Path(args.input)
    if not pdf_path.exists():
        print(f"ERROR: File not found: {pdf_path}")
        sys.exit(1)
    if pdf_path.suffix.lower() != ".pdf":
        print(f"ERROR: Not a PDF file: {pdf_path}")
        sys.exit(1)

    output_path = Path(args.output) if args.output else pdf_path.with_suffix(".md")

    page_range = None
    if args.page_range.strip():
        page_range = parse_page_range(args.page_range.strip())
        print(f"  Page range: {page_range[0]}–{page_range[-1]} ({len(page_range)} pages)")

    print("Loading models (first run downloads ~3 GB, subsequent runs are instant)...")
    models = create_model_dict(device="cpu", dtype=torch.float32)
    print("Models loaded.")

    markdown = convert_pdf(pdf_path, page_range=page_range, models=models)

    output_path.write_text(markdown, encoding="utf-8")
    print(f"\nWritten: {output_path}")


if __name__ == "__main__":
    main()
