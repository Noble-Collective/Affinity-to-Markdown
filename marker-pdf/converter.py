"""
converter.py — Marker PDF → Markdown conversion logic.

Pure conversion module — no HTTP or web code here.
Uses model_loader.get_models() so the 5 Surya models are
loaded once at startup and reused across requests.
"""
import logging
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Trimmed processor list ────────────────────────────────────────────────────
# Only processors needed for prose books.
# Removed: all 10 LLM* processors, CodeProcessor, EquationProcessor,
# FootnoteProcessor, TableProcessor + variants, LineNumbersProcessor,
# ReferenceProcessor, DebugProcessor.
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

# ── Marker configuration ────────────────────────────────────────────────────
# Keys map directly to processor attributes via assign_config().
# See ARCHITECTURE.md for full rationale on each setting.
MARKER_CONFIG: dict = {
    # SectionHeaderProcessor: extend KMeans clustering to H6
    # (default is 4, which would collapse verse labels into H4)
    "level_count": 6,
    # Default heading level for unclustered headers (H3 not H2)
    "default_level": 3,
    # IgnoreTextProcessor: catch running headers on 15%+ of pages
    "common_element_threshold": 0.15,
    # IgnoreTextProcessor: slightly looser fuzzy match (default 90)
    "text_match_threshold": 85,
    # PDF has embedded text — OCR is not needed
    "disable_ocr": True,
    # Single worker on Cloud Run (no multiprocessing)
    "pdftext_workers": 1,
    # Lower DPI for layout model (CPU inference, no GPU)
    "DocumentBuilder_lowres_image_dpi": 72,
    # Don't extract images into the output
    "disable_image_extraction": True,
}


def parse_page_range(s: str) -> list[int]:
    """
    Parse a human-friendly page range string into a list of 0-indexed page numbers.

    Accepts:
      "62-200"      → list(range(62, 201))
      "62,63,64"    → [62, 63, 64]
      "0-10,20-30"  → mixed ranges
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
) -> str:
    """
    Convert a PDF file to Markdown using Marker.

    Args:
        pdf_path:   Path to the input PDF.
        page_range: Optional list of 0-indexed page numbers to convert.
                    Useful for skipping front matter.
                    Example: list(range(62, 200)) for Session 1 of Homestead.

    Returns:
        Markdown string.

    Raises:
        RuntimeError: if models are not loaded yet.
    """
    import model_loader
    from marker.converters.pdf import PdfConverter

    models = model_loader.get_models()  # raises if not ready

    config = dict(MARKER_CONFIG)
    if page_range is not None:
        config["page_range"] = page_range

    # PdfConverter calls strings_to_classes() on processor_list internally
    converter = PdfConverter(
        artifact_dict=models,
        processor_list=PROCESSOR_LIST,
        config=config,
        # renderer defaults to MarkdownRenderer
    )

    size_kb = pdf_path.stat().st_size // 1024
    pages_info = f", pages {page_range[0]}–{page_range[-1]}" if page_range else ""
    logger.info(f"Converting {pdf_path.name} ({size_kb} KB{pages_info})")

    rendered = converter(str(pdf_path))

    logger.info(
        f"Done: {len(rendered.markdown):,} chars, "
        f"{len(rendered.markdown.splitlines())} lines"
    )
    return rendered.markdown
