#!/usr/bin/env python3
"""
pdf_to_markdown.py — Extract text from PDF files into clean Markdown.

Uses PyMuPDF (fitz) for text extraction with per-span font metadata.
Font → Markdown role mapping is driven by pdf_styles.yaml in the
template folder (same template system as afpub conversion).

USAGE
─────
  python pdf_to_markdown.py book.pdf
      → writes book.md alongside the source file

  python pdf_to_markdown.py book.pdf output.md
      → explicit output path

  python pdf_to_markdown.py --dump-fonts book.pdf
      → calibration mode: prints all (font, size) combinations found,
        their run counts, and sample text.  Use this to build pdf_styles.yaml
        for a new book or template.

REQUIREMENTS
────────────
  Python 3.8+   pymupdf >= 1.23   (pip install pymupdf)
  pdf_styles.yaml must live in the same folder as this script, or be
  supplied via the template system (templates/<name>/pdf_styles.yaml).

pdf_styles.yaml FORMAT
──────────────────────
  fonts:
    - font: "TimesNewRomanPS-BoldMT"
      size: 24.0
      markdown: "#"

    - font: "*"          # wildcard — matches any font at this size
      size: 18.0
      markdown: "##"

    - font: "ArialMT"
      size: 10.5
      markdown: ""       # plain body text

  fallback: "warn"       # "body" | "skip" | "warn"

Sizes are matched to the nearest 0.5 pt.  Run --dump-fonts first to find
the exact font names and sizes Affinity Publisher embedded in your PDF.
"""

import glob
import re
import sys
from collections import Counter
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None  # type: ignore


# ────────────────────────────────────────────────────────────────────────────────
# Minimal YAML parser
# ────────────────────────────────────────────────────────────────────────────────

def _load_pdf_styles(yaml_path: Path) -> tuple[dict, str]:
    """
    Parse pdf_styles.yaml.
    Returns (font_map, fallback).
    font_map: { (font_name, size_bucket) → markdown_role }
    size_bucket = float rounded to nearest 0.5 pt.
    Use font_name "*" as a wildcard that matches any font at that size.
    """
    font_map: dict[tuple, str] = {}
    fallback = "warn"

    if not yaml_path.exists():
        return font_map, fallback

    lines = yaml_path.read_text(encoding="utf-8").splitlines()
    current: dict = {}
    in_fonts = False

    def _flush(c: dict) -> None:
        if "font" in c and "markdown" in c:
            key = (c["font"], _size_bucket(c.get("size", 0)))
            font_map[key] = c["markdown"]

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line == "fonts:":
            in_fonts = True
            continue
        if line.startswith("fallback:"):
            fallback = line.split(":", 1)[1].strip().strip("\"'")
            continue
        if not in_fonts:
            continue
        if line.startswith("- font:"):
            _flush(current)
            current = {"font": line.split(":", 1)[1].strip().strip("\"'")}
        elif ":" in line and not line.startswith("-"):
            k, _, v = line.partition(":")
            k, v = k.strip(), v.strip().strip("\"'")
            if k == "size":
                current["size"] = float(v)
            elif k in ("markdown", "name"):
                current[k] = v

    _flush(current)
    return font_map, fallback


def _size_bucket(size: float) -> float:
    """Round to nearest 0.5 pt for fuzzy font-size matching."""
    return round(float(size) * 2) / 2


# ────────────────────────────────────────────────────────────────────────────────
# Font discovery helpers
# ────────────────────────────────────────────────────────────────────────────────

def _iter_text_spans(doc):
    """Yield every text span across all pages."""
    for page in doc:
        for block in page.get_text("dict", sort=True)["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    yield span


def _detect_body_font(doc) -> tuple[str, float]:
    """
    Return (font_name, size_bucket) for the most frequently used
    font combination (by character count).  This is almost always the
    body text font.
    """
    counts: Counter = Counter()
    for span in _iter_text_spans(doc):
        text = span["text"].strip()
        if text and any(c.isalpha() for c in text):
            key = (span["font"], _size_bucket(span["size"]))
            counts[key] += len(text)
    return counts.most_common(1)[0][0] if counts else ("", 10.0)


# ────────────────────────────────────────────────────────────────────────────────
# --dump-fonts calibration mode
# ────────────────────────────────────────────────────────────────────────────────

def _dump_fonts(pdf_path: Path) -> None:
    """
    Print every (font, size) combination found in the PDF with
    character-count totals and sample text.  Calibration tool for
    building pdf_styles.yaml.
    """
    if fitz is None:
        print("ERROR: PyMuPDF not installed (pip install pymupdf)")
        return

    doc = fitz.open(str(pdf_path))
    counts: Counter = Counter()
    samples: dict = {}

    for span in _iter_text_spans(doc):
        text = span["text"].strip()
        if not text or not any(c.isalpha() for c in text):
            continue
        key = (span["font"], _size_bucket(span["size"]))
        counts[key] += len(text)
        if key not in samples:
            samples[key] = text[:70]

    body_key = counts.most_common(1)[0][0] if counts else None

    print(f"\n{'Font Name':<55} {'Size':>5}  {'Chars':>6}  Status   Sample")
    print("─" * 110)
    for (font, size), count in sorted(
        counts.items(), key=lambda x: (-x[0][1], x[0][0])
    ):
        sample = samples.get((font, size), "")
        status = "BODY    " if (font, size) == body_key else "        "
        print(f"{font:<55} {size:>5.1f}  {count:>6}  {status} {sample}")

    print(f"\nTotal unique font/size combinations: {len(counts)}")
    print(
        "\nBuild pdf_styles.yaml by mapping each combination to a markdown role."
        "\nThe BODY font maps to markdown: \"\" (plain body text)."
        "\nLarger/bolder fonts typically map to heading levels (#, ##, ###, etc.)."
        "\nRun this report after exporting from Affinity Publisher with embedded fonts.\n"
    )


# ────────────────────────────────────────────────────────────────────────────────
# Role resolution
# ────────────────────────────────────────────────────────────────────────────────

def _auto_role(font_name: str, size_b: float, body_size: float) -> str:
    """
    Heuristic role when the font/size is not in the style map.
    Uses size ratio relative to body and font-name keywords as signals.
    """
    fname = font_name.lower()
    is_bold = "bold" in fname
    is_italic = "italic" in fname or "oblique" in fname

    if body_size > 0:
        ratio = size_b / body_size
        if ratio >= 1.9:
            return "#"
        elif ratio >= 1.6:
            return "##"
        elif ratio >= 1.35:
            return "###"
        elif ratio >= 1.15 and is_bold:
            return "####"
        elif ratio >= 1.05 and is_bold:
            return "#####"

    if is_bold and not is_italic:
        return "bold"
    if is_italic and not is_bold:
        return "italic"
    return ""


def _resolve_role(
    font_name: str,
    size: float,
    font_map: dict,
    body_size: float,
    fallback: str,
    warnings: list,
) -> str:
    size_b = _size_bucket(size)
    # Exact (font, size) match
    if (font_name, size_b) in font_map:
        return font_map[(font_name, size_b)]
    # Wildcard — any font at this size
    if ("*", size_b) in font_map:
        return font_map[("*", size_b)]
    # Auto-detect from size ratio and font name
    auto = _auto_role(font_name, size_b, body_size)
    if auto:
        return auto
    # Fallback
    if fallback == "warn":
        warnings.append(f"Unmapped font: {font_name!r} @ {size:.1f}pt")
    elif fallback == "skip":
        return "SKIP"
    return ""


# ────────────────────────────────────────────────────────────────────────────────
# Block → Markdown
# ────────────────────────────────────────────────────────────────────────────────

def _is_page_artifact(block: dict, page_height: float) -> bool:
    """
    Heuristically detect page numbers, running headers, and footers.
    A block in the top or bottom 4% of the page that contains fewer
    than 30 characters is treated as a layout artifact and skipped.
    """
    bbox = block.get("bbox", (0, 0, 0, 0))
    y_top, y_bot = bbox[1], bbox[3]
    if y_top < page_height * 0.04 or y_bot > page_height * 0.96:
        total = "".join(
            span["text"]
            for line in block.get("lines", [])
            for span in line.get("spans", [])
        ).strip()
        if len(total) < 30:
            return True
    return False


def _span_is_bold(span: dict) -> bool:
    fname = span["font"].lower()
    return "bold" in fname or bool(span.get("flags", 0) & 16)


def _span_is_italic(span: dict) -> bool:
    fname = span["font"].lower()
    return "italic" in fname or "oblique" in fname or bool(span.get("flags", 0) & 2)


def _block_to_md(
    block: dict,
    font_map: dict,
    body_font: str,
    body_size: float,
    fallback: str,
    warnings: list,
) -> list[str]:
    """
    Convert one PDF text block into a list of Markdown paragraph strings.

    Strategy:
    - Determine the dominant font/size for the block (by character count).
    - Look up that font in the style map to get the block-level role.
    - Heading blocks collapse all spans into a single prefixed line.
    - Body blocks reconstruct line-by-line with inline bold/italic
      detection based on per-span font differences from the body font.
    - List items are detected from leading bullet/number characters.
    """
    if block.get("type") != 0:
        return []

    all_spans = [
        span
        for line in block.get("lines", [])
        for span in line.get("spans", [])
        if span["text"].strip()
    ]
    if not all_spans:
        return []

    # Dominant font = most characters across all content spans
    font_chars: Counter = Counter()
    for span in all_spans:
        text = span["text"].strip()
        if any(c.isalpha() for c in text):
            key = (span["font"], _size_bucket(span["size"]))
            font_chars[key] += len(text)

    if not font_chars:
        return []

    dom_font, dom_size_b = font_chars.most_common(1)[0][0]
    block_role = _resolve_role(
        dom_font, dom_size_b, font_map, body_size, fallback, warnings
    )

    if block_role == "SKIP":
        return []

    # ── Heading block ────────────────────────────────────────────────────────
    if block_role and block_role.startswith("#"):
        text = " ".join(
            span["text"].strip() for span in all_spans if span["text"].strip()
        )
        text = " ".join(text.split())  # normalise whitespace
        if text and any(c.isalpha() for c in text):
            return [f"{block_role} {text}"]
        return []

    # ── Body / blockquote / list block ─ reconstruct line by line ──────────
    result_lines: list[str] = []
    current_parts: list[str] = []
    prev_y: float | None = None

    body_is_bold = "bold" in body_font.lower()
    body_is_italic = "italic" in body_font.lower() or "oblique" in body_font.lower()

    for line in block.get("lines", []):
        spans = [s for s in line.get("spans", []) if s["text"].strip()]
        if not spans:
            continue

        line_y = line["bbox"][1]
        # New visual line: more than 3 pt gap in Y
        if prev_y is not None and abs(line_y - prev_y) > 3 and current_parts:
            result_lines.append("".join(current_parts))
            current_parts = []

        for span in spans:
            text = span["text"]
            if not text.strip():
                current_parts.append(text)
                continue

            # Inline bold/italic: only applied inside body-text blocks,
            # and only when this span differs from the body font style.
            if block_role == "":
                span_size_b = _size_bucket(span["size"])
                size_matches_body = abs(span_size_b - body_size) < 0.6
                is_bold = _span_is_bold(span)
                is_italic = _span_is_italic(span)

                if size_matches_body and not body_is_bold and not body_is_italic:
                    if is_bold and is_italic:
                        current_parts.append(f"***{text}***")
                    elif is_bold:
                        current_parts.append(f"**{text}**")
                    elif is_italic:
                        current_parts.append(f"*{text}*")
                    else:
                        current_parts.append(text)
                else:
                    current_parts.append(text)
            else:
                current_parts.append(text)

        prev_y = line_y

    if current_parts:
        result_lines.append("".join(current_parts))

    # Apply block-level role
    output: list[str] = []
    for raw in result_lines:
        raw = raw.strip()
        if not raw or not any(c.isalpha() or c.isdigit() for c in raw):
            continue

        # Detect list items from leading characters (body blocks only)
        if block_role == "":
            bullet_m = re.match(r"^[\u2022\u2023\u25e6\-\*]\s+(.+)$", raw)
            num_m = re.match(r"^(\d+)[.)]\s+(.+)$", raw)
            if bullet_m:
                output.append(f"- {bullet_m.group(1)}")
                continue
            if num_m:
                output.append(f"{num_m.group(1)}. {num_m.group(2)}")
                continue

        if block_role == ">":
            output.append(f"> {raw}")
        elif block_role == "<<":
            output.append(f"<< {raw}")
        elif block_role == "p_italic":
            output.append(f"*{raw}*")
        elif block_role in ("bold", "italic", ""):
            output.append(raw)
        else:
            # Catch-all for any unmapped role
            output.append(raw)

    return output


# ────────────────────────────────────────────────────────────────────────────────
# Main conversion pipeline
# ────────────────────────────────────────────────────────────────────────────────

def _convert_pdf(
    pdf_path: Path,
    output_path: Path,
    font_map: dict,
    fallback: str,
) -> None:
    """
    Convert a PDF file to Markdown and write the result to output_path.
    """
    if fitz is None:
        raise RuntimeError("PyMuPDF not installed — run: pip install pymupdf")

    print(f"  Reading       {pdf_path.name}")
    doc = fitz.open(str(pdf_path))
    print(f"  Pages         {doc.page_count}")

    body_font, body_size = _detect_body_font(doc)
    print(f"  Body font     {body_font!r} @ {body_size:.1f}pt")

    warnings: list[str] = []
    all_lines: list[str] = []

    for page in doc:
        page_h = page.rect.height
        blocks = page.get_text("dict", sort=True)["blocks"]
        text_blocks = [
            b for b in blocks
            if b.get("type") == 0 and not _is_page_artifact(b, page_h)
        ]
        for block in text_blocks:
            lines = _block_to_md(
                block, font_map, body_font, body_size, fallback, warnings
            )
            for line in lines:
                all_lines.append(line)
            if lines:
                all_lines.append("")  # blank line between blocks

    # Collapse runs of blank lines to a single blank
    final: list[str] = []
    prev_blank = False
    for line in all_lines:
        is_blank = line == ""
        if is_blank and prev_blank:
            continue
        final.append(line)
        prev_blank = is_blank

    output_text = "\n".join(final).strip() + "\n"
    output_path.write_text(output_text, encoding="utf-8")
    print(f"  Written       {output_path}  ({len(final)} lines)")

    if warnings:
        unique_warns = sorted(set(warnings))
        print(f"\n  {len(unique_warns)} font warning(s):")
        for w in unique_warns[:20]:
            print(f"  ⚠  {w}")
        if len(unique_warns) > 20:
            print(f"  … and {len(unique_warns) - 20} more")
        print(
            "\n  Run --dump-fonts to list all fonts, "
            "then update pdf_styles.yaml."
        )


# ────────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ────────────────────────────────────────────────────────────────────────────────

def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(0)

    if fitz is None:
        print("ERROR: PyMuPDF not installed.  Run: pip install pymupdf")
        sys.exit(1)

    dump_mode = False
    if args[0] == "--dump-fonts":
        dump_mode = True
        args = args[1:]

    if not args:
        print("ERROR: No input files specified.")
        sys.exit(1)

    script_dir = Path(__file__).resolve().parent
    styles_path = script_dir / "pdf_styles.yaml"
    font_map, fallback = _load_pdf_styles(styles_path)
    if not dump_mode:
        print(f"Loaded {len(font_map)} font mappings  (fallback: {fallback!r})")

    explicit_output: Path | None = None
    if not dump_mode and len(args) >= 2 and args[-1].lower().endswith(".md"):
        explicit_output = Path(args[-1])
        args = args[:-1]

    input_paths: list[Path] = []
    for arg in args:
        matches = glob.glob(arg)
        if matches:
            input_paths.extend(Path(m) for m in sorted(matches))
        else:
            input_paths.append(Path(arg))

    for i, pdf_path in enumerate(input_paths):
        print(f"\n[{i+1}/{len(input_paths)}] {pdf_path}")
        if not pdf_path.exists():
            print("  SKIP — file not found")
            continue
        if pdf_path.suffix.lower() != ".pdf":
            print("  SKIP — not a .pdf file")
            continue
        try:
            if dump_mode:
                _dump_fonts(pdf_path)
            else:
                out = explicit_output or pdf_path.with_suffix(".md")
                _convert_pdf(pdf_path, out, font_map, fallback)
        except Exception as exc:
            print(f"  ERROR: {exc}")
            import traceback
            traceback.print_exc()

    print("\nDone.")


if __name__ == "__main__":
    main()
