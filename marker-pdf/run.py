#!/usr/bin/env python
"""
run.py - Local runner for PDF to Markdown conversion using Marker.

Architecture:
  1. PyMuPDF builds a font-based heading map from the PDF (accurate, instant)
  2. Marker converts the PDF (paragraph joining, lists, blockquotes)
  3. Post-processing applies the heading map + citation detection + cleanup

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
# Discovered via --dump-fonts analysis. Key: (font_name, size_bucket).
# size_bucket = round(size * 2) / 2  (nearest 0.5pt)
HOMESTEAD_FONT_HEADINGS = {
    ("TimesNewRomanPSMT",        20.0): "#",
    ("TimesNewRomanPS-BoldMT",   20.0): "###",
    ("TimesNewRomanPS-ItalicMT", 14.0): "##",
    ("TimesNewRomanPS-BoldMT",   14.0): "####",
    ("TimesNewRomanPS-BoldMT",   18.0): "####",
    ("TimesNewRomanPS-BoldMT",   12.0): "#####",
}

# Scripture reference citation pattern
_CITATION_RE = re.compile(
    r"^("
    r"[A-Z][a-zA-Z]+\s+\d+:\d+[\d\-–—,;:\s]*"   # e.g. "John 3:16", "Psalm 103:1-22"
    r"|[A-Z][a-zA-Z]+\.\s+\d+:\d+[\d\-–—,;:\s]*"  # e.g. "Mt. 5:3"
    r")$"
)


def size_bucket(size: float) -> float:
    return round(float(size) * 2) / 2


def build_heading_map(pdf_path: Path, page_range=None) -> dict:
    """
    Use PyMuPDF to scan the PDF and build a lookup:
      { normalised_text[:60] -> correct_markdown_prefix }

    This is accurate because it uses actual font metadata, not ML guessing.
    """
    try:
        import fitz
    except ImportError:
        print("Warning: PyMuPDF not installed — heading remapping disabled.")
        return {}

    heading_map = {}
    doc = fitz.open(str(pdf_path))

    pages_to_scan = range(doc.page_count)
    if page_range:
        pages_to_scan = [p for p in page_range if p < doc.page_count]

    for page_idx in pages_to_scan:
        page = doc[page_idx]
        for block in page.get_text("dict", sort=True)["blocks"]:
            if block.get("type") != 0:
                continue

            # Find dominant font for this block (by character count)
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

            # Collect full block text
            text = " ".join(
                span["text"].strip()
                for line in block.get("lines", [])
                for span in line.get("spans", [])
                if span["text"].strip()
            ).strip()
            text = " ".join(text.split())  # normalise whitespace

            if text and len(text) > 2:
                key = re.sub(r"\*+", "", text).strip().lower()[:60]
                heading_map[key] = prefix

    return heading_map


def fix_headings(markdown: str, heading_map: dict) -> str:
    """
    Replace Marker's heading levels with correct ones from the font-based map.
    Only remaps headings that appear in the lookup; leaves others unchanged.
    """
    if not heading_map:
        return markdown

    lines = markdown.splitlines()
    out = []
    for line in lines:
        m = re.match(r'^(#{1,6})\s+(.+)$', line)
        if m:
            content = m.group(2)
            # Normalise: strip bold/italic markers, lowercase, truncate
            clean = re.sub(r'\*+', '', content).strip().lower()[:60]
            if clean in heading_map:
                out.append(f"{heading_map[clean]} {content}")
            else:
                out.append(line)
        else:
            out.append(line)
    return '\n'.join(out)


def fix_citations(markdown: str) -> str:
    """
    Convert standalone short lines to << citations when they:
    - Follow a blockquote line (> ...) or body paragraph, OR
    - Match a scripture reference pattern
    Handles: "Job 1:5", "Isaiah 63:16", "Psalm 103:1-22",
             author attributions like "Philip Bennet Power, *The Sick Man's...*"
    """
    lines = markdown.splitlines()
    out = []
    for i, line in enumerate(lines):
        stripped = line.strip()

        # Check if this is a short standalone line that looks like a citation
        if not stripped or stripped.startswith('#') or stripped.startswith('>') \
                or stripped.startswith('<<') or stripped.startswith('-') \
                or stripped.startswith('*') or len(stripped) > 120:
            out.append(line)
            continue

        # Must be surrounded by blank lines (standalone paragraph)
        prev_blank = (i == 0) or (lines[i-1].strip() == '')
        next_blank = (i == len(lines)-1) or (lines[i+1].strip() == '')

        if not (prev_blank and next_blank):
            out.append(line)
            continue

        # Scripture reference pattern
        if _CITATION_RE.match(stripped):
            out.append(f"<< {stripped}")
            continue

        # Short attribution after a quote (prev non-blank was > or <<)
        prev_content = next(
            (lines[j].strip() for j in range(i-1, -1, -1) if lines[j].strip()), ""
        )
        if prev_content.startswith('>') or prev_content.startswith('<<'):
            if len(stripped) < 80:
                out.append(f"<< {stripped}")
                continue

        out.append(line)
    return '\n'.join(out)


def fix_bullet_numbers(markdown: str) -> str:
    """Convert '- 1. Text' → '1. Text' (Marker combines bullet + number markers)."""
    return re.sub(r'^- (\d+\.)\s', r'\1 ', markdown, flags=re.MULTILINE)


def fix_hyphenation(markdown: str) -> str:
    """
    Merge lines ending with a hyphen into the next non-empty line.
    Handles column-break hyphenation: 'wor-' + 'ship' → 'worship'
    """
    lines = markdown.splitlines()
    out = []
    skip_next_blank = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.rstrip().endswith('-') and len(line.strip()) > 5:
            # Find next non-blank line
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines):
                # Merge: remove hyphen, join with continuation
                merged = line.rstrip()[:-1] + lines[j].lstrip()
                out.append(merged)
                i = j + 1
                continue
        out.append(line)
        i += 1
    return '\n'.join(out)


def post_process(markdown: str, heading_map: dict) -> str:
    """Apply all post-processing passes in order."""
    # Normalise line endings
    markdown = markdown.replace('\r\n', '\n').replace('\r', '\n')
    # Remove image references
    markdown = re.sub(r'^!\[.*?\]\(.*?\)\s*$', '', markdown, flags=re.MULTILINE)
    # Fix heading levels using font data
    markdown = fix_headings(markdown, heading_map)
    # Fix citations
    markdown = fix_citations(markdown)
    # Fix bullet+number list format
    markdown = fix_bullet_numbers(markdown)
    # Fix hyphenation artifacts
    markdown = fix_hyphenation(markdown)
    # Collapse 3+ blank lines to 2
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

    # Step 1: Build accurate heading map from font data (instant)
    print("Building heading map from font data...")
    heading_map = build_heading_map(pdf_path, page_range)
    print(f"Found {len(heading_map)} heading entries.")

    patch_block_relabel()

    # Step 2: Load Marker models and convert
    print("Loading models (~30s from disk)...")
    import torch
    from marker.models import create_model_dict
    models = create_model_dict(device="cpu", dtype=torch.float32)
    print("Models loaded.")

    # ── Marker configuration — iteration 5 ───────────────────────────────
    # Key change: heading levels are now handled by PyMuPDF post-processing,
    # so we no longer fight Marker's KMeans for heading assignment.
    # block_relabel_str removed — not needed since headings are remapped anyway.
    # All other improvements from previous iterations retained.
    config = {
        # Heading: let Marker assign whatever level it wants — we remap in post-processing
        "level_count": 4,
        "default_level": 3,
        # Running header suppression
        "common_element_threshold": 0.15,
        "text_match_threshold": 85,
        # Blockquote detection (13/23 achieved in iter 3/4)
        "BlockquoteProcessor_min_x_indent": 0.01,
        "BlockquoteProcessor_x_start_tolerance": 0.05,
        "BlockquoteProcessor_x_end_tolerance": 0.05,
        # Multi-column text joining
        "TextProcessor_column_gap_ratio": 0.06,
        # Strip link annotations
        "disable_links": True,
        # Performance
        "disable_ocr": True,
        "pdftext_workers": 1,
        "DocumentBuilder_lowres_image_dpi": 72,
        "disable_image_extraction": True,
        "extract_images": False,
    }

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

    # Step 3: Post-process with heading remapping + citation detection + cleanup
    print("Post-processing...")
    markdown = post_process(rendered.markdown, heading_map)
    output_path.write_text(markdown, encoding="utf-8")
    lines = len(markdown.splitlines())
    print(f"Done! Written to: {output_path} ({lines} lines)")


if __name__ == "__main__":
    main()
