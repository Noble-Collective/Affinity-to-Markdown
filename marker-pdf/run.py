#!/usr/bin/env python
"""
run.py - Local runner for PDF to Markdown conversion.

Architecture (iteration 6):
  - Marker with force_layout_block="Text" skips the 6-minute image layout
    detection step. pdftext still runs (fast, handles 2-column ordering).
  - All structural roles (headings, blockquotes, citations, etc.) are
    assigned by PyMuPDF font-based post-processing.
  - Conversion time: ~30s model load + ~30s conversion (vs 6+ min before).

Usage:
  python run.py path/to/book.pdf
  python run.py path/to/book.pdf --page-range 62-200
  python run.py path/to/book.pdf output.md
"""
import sys
import re
import argparse
import logging
from pathlib import Path

logging.basicConfig(level=logging.WARNING)


# ── Font → Heading map for Homestead book ────────────────────────────────────
HOMESTEAD_FONT_HEADINGS = {
    ("TimesNewRomanPSMT",        20.0): "#",
    ("TimesNewRomanPS-BoldMT",   20.0): "###",
    ("TimesNewRomanPS-ItalicMT", 14.0): "##",
    ("TimesNewRomanPS-BoldMT",   14.0): "####",
    ("TimesNewRomanPS-BoldMT",   18.0): "####",
    ("TimesNewRomanPS-BoldMT",   12.0): "#####",
    # Large decorative fonts on section divider pages — skip
    ("TimesNewRomanPSMT",        48.0): "SKIP",
    ("TimesNewRomanPSMT",        28.0): "SKIP",
}

# Running header signature: mixed BoldMT@14 (drop-cap) + BoldMT@9.5 (small-caps)
_RUNNING_HEADER_FONTS = {
    ("TimesNewRomanPS-BoldMT", 14.0),
    ("TimesNewRomanPS-BoldMT", 9.5),
}

# Scripture citation pattern
_CITATION_RE = re.compile(
    r"^("
    r"[A-Z][a-zA-Z]+\s+\d+:\d+[\d\-–—,;:\s]*"
    r"|[A-Z][a-zA-Z]+\.\s+\d+:\d+[\d\-–—,;:\s]*"
    r")$"
)


def size_bucket(size: float) -> float:
    return round(float(size) * 2) / 2


def build_heading_map(pdf_path: Path, page_range=None) -> dict:
    """
    Use PyMuPDF to scan the PDF and build a lookup:
      { normalised_text[:60] -> correct_markdown_prefix }
    Accurate because it uses actual font metadata.
    """
    try:
        import fitz
    except ImportError:
        print("Warning: PyMuPDF not installed — heading remapping disabled.")
        return {}

    heading_map = {}
    doc = fitz.open(str(pdf_path))
    pages_to_scan = range(doc.page_count) if page_range is None else [
        p for p in page_range if p < doc.page_count
    ]

    for page_idx in pages_to_scan:
        page = doc[page_idx]
        for block in page.get_text("dict", sort=True)["blocks"]:
            if block.get("type") != 0:
                continue

            font_chars: dict = {}
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    t = span["text"].strip()
                    if any(c.isalpha() for c in t):
                        key = (span["font"], size_bucket(span["size"]))
                        font_chars[key] = font_chars.get(key, 0) + len(t)

            if not font_chars:
                continue

            dom_font = max(font_chars, key=font_chars.get)
            if dom_font not in HOMESTEAD_FONT_HEADINGS:
                continue

            prefix = HOMESTEAD_FONT_HEADINGS[dom_font]
            if prefix == "SKIP":
                continue

            text = " ".join(
                span["text"].strip()
                for line in block.get("lines", [])
                for span in line.get("spans", [])
                if span["text"].strip()
            ).strip()
            text = " ".join(text.split())

            if text and len(text) > 2:
                key = re.sub(r"\*+", "", text).strip().lower()[:60]
                heading_map[key] = prefix

    return heading_map


def build_skip_set(pdf_path: Path, page_range=None) -> set:
    """
    Build a set of text snippets to skip entirely:
    - Running headers (BoldMT@14 + BoldMT@9.5 mixed blocks)
    - Page numbers (short all-digit blocks)
    - Large decorative section divider text
    """
    try:
        import fitz
    except ImportError:
        return set()

    skip_set = set()
    doc = fitz.open(str(pdf_path))
    pages_to_scan = range(doc.page_count) if page_range is None else [
        p for p in page_range if p < doc.page_count
    ]

    for page_idx in pages_to_scan:
        page = doc[page_idx]
        for block in page.get_text("dict", sort=True)["blocks"]:
            if block.get("type") != 0:
                continue

            font_set = set()
            text = ""
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    t = span["text"].strip()
                    if t:
                        font_set.add((span["font"], size_bucket(span["size"])))
                        text += span["text"]

            text = " ".join(text.split()).strip()
            if not text:
                continue

            # Running header: has BOTH 14pt bold (drop cap) AND 9.5pt bold (small caps)
            if _RUNNING_HEADER_FONTS.issubset(font_set):
                skip_set.add(text.lower()[:60])
                continue

            # Page numbers: short all-digit text
            if re.match(r"^\d{1,3}$", text):
                skip_set.add(text.lower()[:60])
                continue

            # Decorative large fonts (48pt, 28pt etc.)
            for font, size in font_set:
                if size >= 24.0:
                    skip_set.add(text.lower()[:60])
                    break

    return skip_set


def fix_headings(markdown: str, heading_map: dict, skip_set: set) -> str:
    """Replace Marker's heading levels with correct ones from font map.
    Also removes lines whose content is in the skip set."""
    if not heading_map and not skip_set:
        return markdown

    lines = markdown.splitlines()
    out = []
    for line in lines:
        # Check skip set (running headers, page numbers, decorative text)
        clean_check = re.sub(r"[#*_>]", "", line).strip().lower()[:60]
        if clean_check in skip_set:
            continue

        m = re.match(r'^(#{1,6})\s+(.+)$', line)
        if m:
            content = m.group(2)
            clean = re.sub(r'\*+', '', content).strip().lower()[:60]
            if clean in skip_set:
                continue
            if clean in heading_map:
                out.append(f"{heading_map[clean]} {content}")
            else:
                out.append(line)
        else:
            out.append(line)
    return '\n'.join(out)


def fix_citations(markdown: str) -> str:
    """Convert standalone short reference lines to << citations."""
    lines = markdown.splitlines()
    out = []
    for i, line in enumerate(lines):
        stripped = line.strip()

        if not stripped or stripped.startswith('#') or stripped.startswith('>') \
                or stripped.startswith('<<') or stripped.startswith('-') \
                or stripped.startswith('*') or len(stripped) > 120:
            out.append(line)
            continue

        prev_blank = (i == 0) or (lines[i-1].strip() == '')
        next_blank = (i == len(lines)-1) or (lines[i+1].strip() == '')
        if not (prev_blank and next_blank):
            out.append(line)
            continue

        # Scripture reference pattern
        if _CITATION_RE.match(stripped):
            out.append(f"<< {stripped}")
            continue

        # Short attribution after a blockquote or existing citation
        prev_content = next(
            (lines[j].strip() for j in range(i-1, -1, -1) if lines[j].strip()), ""
        )
        if (prev_content.startswith('>') or prev_content.startswith('<<')) \
                and len(stripped) < 80:
            out.append(f"<< {stripped}")
            continue

        out.append(line)
    return '\n'.join(out)


def fix_bullet_numbers(markdown: str) -> str:
    """Convert '- 1. Text' → '1. Text'."""
    return re.sub(r'^- (\d+\.)\s', r'\1 ', markdown, flags=re.MULTILINE)


def fix_hyphenation(markdown: str) -> str:
    """Merge lines ending with hyphen into the next non-blank line."""
    lines = markdown.splitlines()
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.rstrip().endswith('-') and len(line.strip()) > 5:
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines):
                out.append(line.rstrip()[:-1] + lines[j].lstrip())
                i = j + 1
                continue
        out.append(line)
        i += 1
    return '\n'.join(out)


def post_process(markdown: str, heading_map: dict, skip_set: set) -> str:
    """Apply all post-processing passes in order."""
    markdown = markdown.replace('\r\n', '\n').replace('\r', '\n')
    markdown = re.sub(r'^!\[.*?\]\(.*?\)\s*$', '', markdown, flags=re.MULTILINE)
    markdown = re.sub(r'^-{20,}\s*$', '', markdown, flags=re.MULTILINE)  # page separators
    markdown = fix_headings(markdown, heading_map, skip_set)
    markdown = fix_citations(markdown)
    markdown = fix_bullet_numbers(markdown)
    markdown = fix_hyphenation(markdown)
    markdown = re.sub(r'\n{3,}', '\n\n', markdown)
    return markdown.strip() + '\n'


def patch_block_relabel():
    """Patch Marker bug: top_k.get() returns None for some blocks."""
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
                if confidence is None:
                    continue  # BUG FIX
                if confidence > confidence_thresh:
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
    BlockRelabelProcessor.__call__ = patched_call


def main():
    parser = argparse.ArgumentParser(description="Convert PDF to Markdown using Marker.")
    parser.add_argument("input", help="Path to the PDF file")
    parser.add_argument("output", nargs="?", help="Output .md path (optional)")
    parser.add_argument("--page-range", default="",
                        help="0-indexed page range e.g. '62-200'")
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

    # Build font-based maps BEFORE loading Marker (fast, ~1s)
    print("Building heading map and skip set from font data...")
    heading_map = build_heading_map(pdf_path, page_range)
    skip_set = build_skip_set(pdf_path, page_range)
    print(f"  {len(heading_map)} heading entries, {len(skip_set)} skip entries.")

    patch_block_relabel()

    print("Loading models (~30s from disk)...")
    import torch
    from marker.models import create_model_dict
    models = create_model_dict(device="cpu", dtype=torch.float32)
    print("Models loaded.")

    # ── Marker configuration — iteration 6 ───────────────────────────────
    #
    # force_layout_block="Text": Skip the 6-minute Surya image layout
    # detection step entirely. Marker's pdftext still extracts text in
    # correct reading order (handles 2-column layouts). All structural
    # roles are assigned by PyMuPDF post-processing instead.
    #
    # Tradeoff: lose Marker's blockquote spatial detection (was 13/23).
    # Will re-implement blockquote detection via 8pt font size in a future
    # iteration if needed.

    config = {
        # Skip image-based layout detection — use text-only extraction
        "force_layout_block": "Text",
        # Running header suppression still works on text content
        "common_element_threshold": 0.15,
        "text_match_threshold": 85,
        # Performance
        "disable_ocr": True,
        "pdftext_workers": 1,
        "DocumentBuilder_lowres_image_dpi": 72,
        "disable_image_extraction": True,
        "extract_images": False,
        "disable_links": True,
    }

    if page_range:
        config["page_range"] = page_range

    # Trimmed processor list — remove layout-dependent processors
    # since all blocks are Text with force_layout_block
    processor_list = [
        "marker.processors.order.OrderProcessor",
        "marker.processors.ignoretext.IgnoreTextProcessor",
        "marker.processors.text.TextProcessor",
        "marker.processors.blank_page.BlankPageProcessor",
    ]

    from marker.converters.pdf import PdfConverter
    print(f"Converting {pdf_path.name} (text-only mode, no image layout detection)...")
    converter = PdfConverter(
        artifact_dict=models,
        processor_list=processor_list,
        config=config,
    )
    rendered = converter(str(pdf_path))

    print("Post-processing...")
    markdown = post_process(rendered.markdown, heading_map, skip_set)
    output_path.write_text(markdown, encoding="utf-8")
    lines = len(markdown.splitlines())
    print(f"Done! Written to: {output_path} ({lines} lines)")


if __name__ == "__main__":
    main()
