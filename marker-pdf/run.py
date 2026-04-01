#!/usr/bin/env python
"""
run.py - Local runner for PDF to Markdown conversion.

Architecture (iteration 7):
  - Marker handles text extraction, paragraph joining, list detection,
    blockquote spatial detection.
  - PyMuPDF builds accurate heading map + skip set from font data.
  - Post-processing: heading remapping, citation detection, blockquote
    detection via 8pt font, verse label extraction, hyphenation fix.

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
    ("TimesNewRomanPSMT",        48.0): "SKIP",
    ("TimesNewRomanPSMT",        28.0): "SKIP",
}

_RUNNING_HEADER_FONTS = {
    ("TimesNewRomanPS-BoldMT", 14.0),
    ("TimesNewRomanPS-BoldMT", 9.5),
}

_CITATION_RE = re.compile(
    r"^("
    r"[A-Z][a-zA-Z]+\s+\d+:\d+[\d\-–—,;:\s]*"
    r"|[A-Z][a-zA-Z]+\.\s+\d+:\d+[\d\-–—,;:\s]*"
    r")$"
)

# Verse label pattern: "VERSE 1", "VERSE 2", etc.
_VERSE_LABEL_RE = re.compile(r"^VERSE\s+(\d+)(.*)", re.DOTALL)


def size_bucket(size: float) -> float:
    return round(float(size) * 2) / 2


def normalise_key(text: str) -> str:
    """Normalise text for heading map lookup.
    Strips bold/italic markers, lowercases, normalises quotes/apostrophes,
    collapses whitespace, truncates to 60 chars.
    """
    t = re.sub(r"\*+", "", text)
    t = t.replace("\u2018", "'").replace("\u2019", "'")  # curly single quotes
    t = t.replace("\u201c", '"').replace("\u201d", '"')  # curly double quotes
    t = t.replace("\u2013", "-").replace("\u2014", "-")  # en/em dash
    t = " ".join(t.split()).strip().lower()
    return t[:60]


def build_heading_map(pdf_path: Path, page_range=None) -> dict:
    """
    Use PyMuPDF to build {normalised_text -> markdown_prefix} for all
    heading-font blocks in the PDF.
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

            # Collect only spans from the dominant heading font
            # (avoids picking up trailing small-caps or mixed content)
            text_parts = []
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    sk = (span["font"], size_bucket(span["size"]))
                    if sk == dom_font and span["text"].strip():
                        text_parts.append(span["text"].strip())

            text = " ".join(text_parts).strip()
            text = " ".join(text.split())

            if text and len(text) > 2:
                key = normalise_key(text)
                heading_map[key] = prefix

    return heading_map


def build_skip_set(pdf_path: Path, page_range=None) -> set:
    """
    Build set of normalised text snippets to remove from output:
    running headers, page numbers, decorative large text.
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

            if _RUNNING_HEADER_FONTS.issubset(font_set):
                skip_set.add(normalise_key(text))
                continue

            if re.match(r"^\d{1,3}$", text):
                skip_set.add(normalise_key(text))
                continue

            for font, size in font_set:
                if size >= 24.0:
                    skip_set.add(normalise_key(text))
                    break

    return skip_set


def build_blockquote_set(pdf_path: Path, page_range=None) -> tuple[set, set]:
    """
    Scan for 8pt text blocks. Returns:
      blockquote_set: normalised first-60-chars of long 8pt blocks (>80 chars)
      citation_set:   normalised text of short 8pt blocks (<=80 chars)
    """
    try:
        import fitz
    except ImportError:
        return set(), set()

    bq_set = set()
    cit_set = set()
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
            text = ""
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    t = span["text"]
                    if t.strip():
                        key = (span["font"], size_bucket(span["size"]))
                        font_chars[key] = font_chars.get(key, 0) + len(t.strip())
                    text += t

            if not font_chars:
                continue

            dom_font = max(font_chars, key=font_chars.get)
            # 8pt Regular = blockquote or citation
            if dom_font not in (
                ("TimesNewRomanPSMT", 8.0),
                ("TimesNewRomanPS-ItalicMT", 8.0),
            ):
                continue

            text = " ".join(text.split()).strip()
            if not text or not any(c.isalpha() for c in text):
                continue

            key = normalise_key(text[:60])
            if len(text) > 80:
                bq_set.add(key)
            else:
                cit_set.add(key)

    return bq_set, cit_set


def fix_headings(markdown: str, heading_map: dict, skip_set: set) -> str:
    """
    Three passes:
    1. Remove lines in skip_set (running headers, page numbers)
    2. Remap existing heading lines to correct levels
    3. Promote body text lines that match heading_map (catches headings
       Marker classified as Text rather than SectionHeader)
    """
    lines = markdown.splitlines()
    out = []
    for line in lines:
        clean_check = normalise_key(re.sub(r"[#>]", "", line))
        if clean_check in skip_set:
            continue

        m = re.match(r'^(#{1,6})\s+(.+)$', line)
        if m:
            content = m.group(2)
            clean = normalise_key(content)
            if clean in skip_set:
                continue
            if clean in heading_map:
                out.append(f"{heading_map[clean]} {content}")
            else:
                out.append(line)
        else:
            # Promote body text lines that should be headings
            # (Marker classified them as Text, not SectionHeader)
            body_clean = normalise_key(line)
            if body_clean in heading_map and line.strip() and len(line.strip()) > 2:
                # Wrap in appropriate bold/italic if needed
                prefix = heading_map[body_clean]
                out.append(f"{prefix} {line.strip()}")
            else:
                out.append(line)

    return '\n'.join(out)


def fix_blockquotes(markdown: str, bq_set: set, cit_set: set) -> str:
    """
    Convert body text lines to > blockquotes or << citations
    when they match PyMuPDF 8pt font blocks.
    """
    if not bq_set and not cit_set:
        return markdown

    lines = markdown.splitlines()
    out = []
    for line in lines:
        stripped = line.strip()
        if not stripped or line.startswith('>') or line.startswith('<<') \
                or line.startswith('#'):
            out.append(line)
            continue

        key = normalise_key(stripped[:60])
        if key in bq_set:
            out.append(f"> {stripped}")
        elif key in cit_set:
            out.append(f"<< {stripped}")
        else:
            out.append(line)

    return '\n'.join(out)


def fix_citations(markdown: str) -> str:
    """Convert standalone short scripture reference lines to << citations."""
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

        if _CITATION_RE.match(stripped):
            out.append(f"<< {stripped}")
            continue

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


def post_process(markdown: str, heading_map: dict, skip_set: set,
                 bq_set: set, cit_set: set) -> str:
    """Apply all post-processing passes in order."""
    markdown = markdown.replace('\r\n', '\n').replace('\r', '\n')
    markdown = re.sub(r'^!\[.*?\]\(.*?\)\s*$', '', markdown, flags=re.MULTILINE)
    markdown = re.sub(r'^-{20,}\s*$', '', markdown, flags=re.MULTILINE)
    markdown = fix_headings(markdown, heading_map, skip_set)
    markdown = fix_blockquotes(markdown, bq_set, cit_set)
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
                    continue
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

    # Step 1: Build all PyMuPDF maps (fast, ~1s)
    print("Building font maps from PDF...")
    heading_map = build_heading_map(pdf_path, page_range)
    skip_set = build_skip_set(pdf_path, page_range)
    bq_set, cit_set = build_blockquote_set(pdf_path, page_range)
    print(f"  {len(heading_map)} headings, {len(skip_set)} skips, "
          f"{len(bq_set)} blockquotes, {len(cit_set)} citations found.")

    patch_block_relabel()

    # Step 2: Marker conversion
    print("Loading models (~30s from disk)...")
    import torch
    from marker.models import create_model_dict
    models = create_model_dict(device="cpu", dtype=torch.float32)
    print("Models loaded.")

    # ── Marker configuration — iteration 7 ───────────────────────────────
    # Back to standard Marker layout detection (not force_layout_block).
    # force_layout_block="Text" was tried in iteration 6 but produced
    # one blob per page — unusable. Marker's layout detection is needed
    # for proper within-page block segmentation.
    #
    # All structural roles now handled by PyMuPDF post-processing:
    # - Headings: font-based remapping with normalise_key() fixing curly quotes
    # - Body text promoted to headings when Marker classifies them as Text
    # - Blockquotes: 8pt font detection
    # - Citations: scripture reference pattern + 8pt short block detection
    config = {
        "level_count": 4,
        "default_level": 3,
        "common_element_threshold": 0.15,
        "text_match_threshold": 85,
        "BlockquoteProcessor_min_x_indent": 0.01,
        "BlockquoteProcessor_x_start_tolerance": 0.05,
        "BlockquoteProcessor_x_end_tolerance": 0.05,
        "TextProcessor_column_gap_ratio": 0.06,
        "disable_links": True,
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

    # Step 3: Post-process
    print("Post-processing...")
    markdown = post_process(rendered.markdown, heading_map, skip_set, bq_set, cit_set)
    output_path.write_text(markdown, encoding="utf-8")
    lines = len(markdown.splitlines())
    print(f"Done! Written to: {output_path} ({lines} lines)")


if __name__ == "__main__":
    main()
