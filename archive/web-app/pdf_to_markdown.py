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
        their character counts, and sample text.  Use this to build
        pdf_styles.yaml for a new template.

REQUIREMENTS
────────────
  Python 3.8+   pymupdf >= 1.23   (pip install pymupdf)
  pdf_styles.yaml lives in the template folder:
    templates/<name>/pdf_styles.yaml

pdf_styles.yaml FORMAT
──────────────────────
  fonts:
    - font: "TimesNewRomanPS-BoldMT"
      size: 20.0
      markdown: "###"        # role for this font+size combination
      name: "Movement Title" # optional human-readable label

    - font: "*"              # wildcard — any font at this size
      size: 18.0
      markdown: ">"

  fallback: "body"           # "body" | "skip" | "warn"

Sizes are matched to the nearest 0.5 pt.  Run --dump-fonts first to
find the exact font names and sizes Affinity Publisher embedded in
your PDF export.

MARKDOWN ROLES
──────────────
  "#" – "######"  Heading levels H1–H6
  ""              Plain body text (join lines within block)
  ">"             Blockquote paragraph
  "<<"            Right-aligned citation / attribution
  "bold"          Inline bold (applied per-span within body)
  "italic"        Inline italic (applied per-span within body)
  "p_italic"      Whole paragraph in italic
  "superscript"   Inline <sup>N</sup> (e.g. verse numbers)
  "SKIP"          Omit entirely
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
    Return (font_name, size_bucket) for the most-used font (by character
    count).  This is almost always the body text font.
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
    character-count totals and sample text.  Calibration tool.
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
        "\nRun this report after exporting from Affinity Publisher with embedded fonts.\n"
    )


# ────────────────────────────────────────────────────────────────────────────────
# Role resolution
# ────────────────────────────────────────────────────────────────────────────────

def _resolve_role(
    font_name: str,
    size_b: float,
    font_map: dict,
    body_size: float,
    fallback: str,
    warnings: list,
) -> str:
    """Look up a (font, size) pair in the font map and return its Markdown role."""
    # Exact match
    if (font_name, size_b) in font_map:
        return font_map[(font_name, size_b)]
    # Wildcard
    if ("*", size_b) in font_map:
        return font_map[("*", size_b)]
    # Auto-heuristic from size ratio and font-name keywords
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
    # Fallback
    if fallback == "warn":
        warnings.append(f"Unmapped font: {font_name!r} @ {size_b:.1f}pt")
    elif fallback == "skip":
        return "SKIP"
    return ""


# ────────────────────────────────────────────────────────────────────────────────
# Block helpers
# ────────────────────────────────────────────────────────────────────────────────

def _is_page_artifact(block: dict, page_height: float) -> bool:
    """
    Detect page numbers, running headers, and footers.
    A block in the top or bottom 5% of the page with fewer than
    40 characters is treated as a layout artifact and skipped.
    """
    bbox = block.get("bbox", (0, 0, 0, 0))
    y_top, y_bot = bbox[1], bbox[3]
    if y_top < page_height * 0.05 or y_bot > page_height * 0.95:
        total = "".join(
            span["text"]
            for line in block.get("lines", [])
            for span in line.get("spans", [])
        ).strip()
        if len(total) < 40:
            return True
    return False


def _span_is_bold(span: dict) -> bool:
    fname = span["font"].lower()
    return "bold" in fname or bool(span.get("flags", 0) & 16)


def _span_is_italic(span: dict) -> bool:
    fname = span["font"].lower()
    return "italic" in fname or "oblique" in fname or bool(span.get("flags", 0) & 2)


# ────────────────────────────────────────────────────────────────────────────────
# Block → Markdown
# ────────────────────────────────────────────────────────────────────────────────

def _block_to_md(
    block: dict,
    font_map: dict,
    body_font: str,
    body_size: float,
    fallback: str,
    warnings: list,
) -> list[str]:
    """
    Convert one PDF text block into Markdown paragraph strings.

    Core design:
    - Determine the dominant font/size for the block to get the block-level role.
    - Heading blocks: collapse all spans into a single prefixed line.
    - Body/quote blocks: join all visual lines within the block into a single
      paragraph string (PDF line breaks are reflowing, not semantic).
    - Inline bold/italic: applied per-span within body blocks when the span
      font differs from the body font in bold/italic status.
    - Special blocks: verse labels (drop-cap + small-caps) and running headers
      (all-caps mixed-size) are detected and handled before role resolution.
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

    # Collect all sizes present in this block
    sizes_present = {_size_bucket(s["size"]) for s in all_spans}

    # ── 1. Verse label detection ───────────────────────────────────────────────
    # Affinity Publisher renders hymn verse labels as drop-cap + small-caps:
    # Bold 10pt "V" + Bold 7pt "ERSE" + Bold 10pt "4"
    # These are always in the same block as the verse body text.
    if 7.0 in sizes_present:
        # Collect the drop-cap + small-caps spans (Bold, ≤10pt)
        label_spans = [
            s for s in all_spans
            if _size_bucket(s["size"]) in (7.0, 10.0) and _span_is_bold(s)
        ]
        # Collect the verse body spans (Regular, 10pt)
        body_spans_by_line: dict[float, list] = {}
        for line in block.get("lines", []):
            line_y = round(line["bbox"][1])
            for span in line.get("spans", []):
                if span["text"].strip() and not _span_is_bold(span) and _size_bucket(span["size"]) == body_size:
                    body_spans_by_line.setdefault(line_y, []).append(span["text"])

        raw_label = "".join(s["text"] for s in label_spans).replace(" ", "")
        m = re.match(r"V(?:ERSE)?(\d+)", raw_label.upper())
        if m:
            result = [f"###### Verse {m.group(1)}"]
            for line_y in sorted(body_spans_by_line):
                line_text = " ".join(body_spans_by_line[line_y]).strip()
                if line_text:
                    result.append(line_text + "  ")  # Markdown hard line break
            return result
        # Unknown 7pt content — skip block
        return []

    # ── 2. Running header detection ────────────────────────────────────────────
    # Drop-cap + small-caps running headers (e.g. "INTRODUCTION SESSION ONE",
    # "SESSION ONE: UNDER GOD'S FATHERLY CARE") have mixed large (14pt) and
    # small (9.5pt) bold spans whose combined text is all-uppercase.
    if 9.5 in sizes_present and any(s >= 12.0 for s in sizes_present):
        full_text = "".join(s["text"] for s in all_spans).strip()
        if full_text and all(
            c.isupper() or c in " :'\'\",-" for c in full_text
        ) and any(c.isalpha() for c in full_text):
            return []

    # ── 3. Page number suppression ─────────────────────────────────────────────
    # Single-block spans that are purely numeric = page numbers
    if len(all_spans) == 1:
        t = all_spans[0]["text"].strip()
        if re.match(r"^\d{1,4}$", t):
            return []

    # ── Determine block-level role ────────────────────────────────────────────
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

    # ── 4. Citation auto-detection ────────────────────────────────────────────
    # Blockquote blocks shorter than 100 chars are attributions/citations.
    if block_role == ">":
        total_chars = sum(len(s["text"].strip()) for s in all_spans)
        if total_chars < 100:
            block_role = "<<"

    # ── Heading block ─────────────────────────────────────────────────────────
    if block_role and block_role.startswith("#"):
        text = " ".join(
            s["text"].strip() for s in all_spans if s["text"].strip()
        )
        text = " ".join(text.split())
        if text and any(c.isalpha() for c in text):
            return [f"{block_role} {text}"]
        return []

    # ── Body / blockquote / citation block ────────────────────────────────────
    # Collect per-visual-line chunks, then join lines into paragraph(s).
    # Within each visual line, apply per-span inline formatting (bold/italic)
    # when the span font differs from the block's dominant style.

    body_is_bold = "bold" in body_font.lower()
    body_is_italic = "italic" in body_font.lower() or "oblique" in body_font.lower()

    # Group spans by visual line (Y coordinate bucket)
    lines_by_y: dict[int, list] = {}
    for line in block.get("lines", []):
        line_y = round(line["bbox"][1])
        for span in line.get("spans", []):
            if span["text"]:  # include spaces too
                lines_by_y.setdefault(line_y, []).append(span)

    # Build one string per visual line with inline markup
    visual_lines: list[str] = []
    for line_y in sorted(lines_by_y):
        parts: list[str] = []
        for span in lines_by_y[line_y]:
            text = span["text"]
            if not text.strip():
                parts.append(text)
                continue

            size_b = _size_bucket(span["size"])
            span_role = _resolve_role(span["font"], size_b, font_map, body_size, [], [])

            if span_role == "SKIP":
                continue

            # Superscript: verse numbers, footnotes (e.g. Bold 6pt)
            if span_role == "superscript":
                parts.append(f"<sup>{text.strip()}</sup>")
                continue

            # Inline italic within blockquote (e.g. book titles in citations)
            if block_role in (">", "<<") and span_role == "italic":
                parts.append(f"*{text.strip()}*")
                continue

            # Inline bold/italic within body blocks
            if block_role == "":
                size_matches_body = abs(size_b - body_size) < 0.6
                is_bold = _span_is_bold(span)
                is_italic = _span_is_italic(span)
                if size_matches_body and not body_is_bold and not body_is_italic:
                    if is_bold and is_italic:
                        parts.append(f"***{text}***")
                    elif is_bold:
                        parts.append(f"**{text}**")
                    elif is_italic:
                        parts.append(f"*{text}*")
                    else:
                        parts.append(text)
                else:
                    parts.append(text)
            else:
                parts.append(text)

        line_text = "".join(parts).strip()
        if line_text:
            visual_lines.append(line_text)

    if not visual_lines:
        return []

    # ── Join visual lines into paragraph(s) ───────────────────────────────────
    # For body, blockquote, and citation blocks: PDF visual line breaks are
    # text reflow, not semantic. Join all lines into a single paragraph.
    # Exception: if a line ends with punctuation that suggests it's a complete
    # sentence AND the next line starts with an uppercase letter or number,
    # keep it as a separate paragraph (handles multi-paragraph blocks).
    paragraphs: list[str] = []
    current_para_parts: list[str] = []

    for i, vline in enumerate(visual_lines):
        if not current_para_parts:
            current_para_parts.append(vline)
        else:
            prev = current_para_parts[-1]
            # Paragraph break heuristic: prev ends with sentence-final punctuation
            # AND current starts with uppercase or quote — treat as new paragraph.
            # But only split if both sides are substantial (not mid-hyphenation).
            ends_sentence = prev.rstrip().endswith(("."  , "!", "?", "\u201d", "'"))
            starts_upper = vline and (vline[0].isupper() or vline[0].isdigit())
            both_long = len(prev) > 60 and len(vline) > 40
            if ends_sentence and starts_upper and both_long:
                paragraphs.append(" ".join(current_para_parts))
                current_para_parts = [vline]
            else:
                # Join with space, trimming duplicate whitespace at boundary
                joined = prev.rstrip() + " " + vline.lstrip()
                current_para_parts[-1] = joined

    if current_para_parts:
        paragraphs.append(" ".join(current_para_parts))

    # ── Apply block-level prefix and list detection ───────────────────────────
    output: list[str] = []
    for para in paragraphs:
        para = para.strip()
        if not para or not any(c.isalpha() or c.isdigit() for c in para):
            continue

        if block_role == "":
            # Detect list items
            bullet_m = re.match(
                r"^[\u2022\u2023\u25e6\u2013\-\*]\s+(.+)$", para
            )
            num_m = re.match(r"^(\d+)[.)]\s+(.+)$", para)
            if bullet_m:
                output.append(f"- {bullet_m.group(1)}")
            elif num_m:
                output.append(f"{num_m.group(1)}. {num_m.group(2)}")
            else:
                output.append(para)
        elif block_role == ">":
            output.append(f"> {para}")
        elif block_role == "<<":
            output.append(f"<< {para}")
        elif block_role == "p_italic":
            output.append(f"*{para}*")
        elif block_role in ("bold", "italic"):
            output.append(para)  # standalone bold/italic blocks render as plain
        else:
            output.append(para)

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

    # Collapse consecutive blank lines to one
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
