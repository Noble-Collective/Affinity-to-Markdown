#!/usr/bin/env python
"""
run.py - Local runner for PDF to Markdown conversion.

All book-specific configuration lives in templates/<template>/pdf_config.yaml.
The conversion logic is fully generic -- font ratios and weight patterns are
used instead of hardcoded font names or absolute sizes.

Usage:
  python run.py path/to/book.pdf                    # full conversion
  python run.py path/to/book.pdf --save-raw         # save Marker output before post-processing
  python run.py raw.md book.pdf --postprocess       # re-run post-processing only (fast)
  python run.py path/to/book.pdf --template homestead
  python run.py path/to/book.pdf --page-range 62-200
  python run.py path/to/book.pdf --dump-fonts       # calibration mode

To enable LLM heading correction:
  export GOOGLE_API_KEY="your-key-here"
  python run.py path/to/book.pdf
"""
import os
import sys
import re
import argparse
import logging
from pathlib import Path

logging.basicConfig(level=logging.WARNING)

SCRIPT_DIR = Path(__file__).resolve().parent


def _load_yaml(path: Path) -> dict:
    import yaml
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_template(template_name: str) -> dict:
    path = SCRIPT_DIR / "templates" / template_name / "pdf_config.yaml"
    if not path.exists():
        print(f"ERROR: Template config not found: {path}")
        sys.exit(1)
    config = _load_yaml(path)
    config["_citation_res"] = [
        re.compile(p) for p in config.get("citation_patterns", [])
    ]
    return config


def size_bucket(size: float) -> float:
    return round(float(size) * 2) / 2


def font_weight(font_name: str) -> str:
    n = font_name.lower()
    if "bolditalic" in n or ("bold" in n and "italic" in n):
        return "bold-italic"
    if "bold" in n:
        return "bold"
    if "italic" in n:
        return "italic"
    return "regular"


def normalise_key(text: str) -> str:
    t = re.sub(r"\*+", "", text)
    t = t.replace("\u2018", "'").replace("\u2019", "'")
    t = t.replace("\u201c", '"').replace("\u201d", '"')
    t = t.replace("\u2013", "-").replace("\u2014", "-")
    t = " ".join(t.split()).strip().lower()
    return t[:60]


def _match_rule(weight: str, ratio: float, rule: dict) -> bool:
    return (rule["weight"] == weight
            and rule["min_ratio"] <= ratio <= rule["max_ratio"])


def detect_body_font(pdf_path: Path, page_range=None) -> tuple:
    import fitz
    doc = fitz.open(str(pdf_path))
    pages = range(doc.page_count) if page_range is None else [
        p for p in page_range if p < doc.page_count]
    freq: dict = {}
    for page_idx in pages:
        page = doc[page_idx]
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0: continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    t = span["text"].strip()
                    if any(c.isalpha() for c in t):
                        key = (span["font"], size_bucket(span["size"]))
                        freq[key] = freq.get(key, 0) + len(t)
    if not freq: return ("unknown", 10.0)
    return max(freq, key=freq.get)


def build_heading_map(pdf_path: Path, cfg: dict, body_size: float, page_range=None) -> dict:
    import fitz
    heading_map = {}
    doc = fitz.open(str(pdf_path))
    pages = range(doc.page_count) if page_range is None else [
        p for p in page_range if p < doc.page_count]
    rules = cfg.get("headings", [])
    skip_ratio = cfg.get("skip_large_ratio", 2.4)
    for page_idx in pages:
        page = doc[page_idx]
        for block in page.get_text("dict", sort=True)["blocks"]:
            if block.get("type") != 0: continue
            font_chars: dict = {}
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    t = span["text"].strip()
                    if any(c.isalpha() for c in t):
                        key = (span["font"], size_bucket(span["size"]))
                        font_chars[key] = font_chars.get(key, 0) + len(t)
            if not font_chars: continue
            dom_font, dom_size = max(font_chars, key=font_chars.get)
            ratio = dom_size / body_size
            weight = font_weight(dom_font)
            if ratio > skip_ratio: continue
            matched_level = None
            for rule in rules:
                if _match_rule(weight, ratio, rule):
                    matched_level = rule["level"]
                    break
            if matched_level is None: continue
            text_parts = []
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    sk = (span["font"], size_bucket(span["size"]))
                    if sk == (dom_font, dom_size) and span["text"].strip():
                        text_parts.append(span["text"].strip())
            text = " ".join(" ".join(text_parts).split()).strip()
            if text and len(text) > 2:
                heading_map[normalise_key(text)] = "#" * matched_level
    return heading_map


def build_skip_set(pdf_path: Path, cfg: dict, body_size: float, page_range=None) -> set:
    import fitz
    skip_set = set()
    doc = fitz.open(str(pdf_path))
    pages = range(doc.page_count) if page_range is None else [
        p for p in page_range if p < doc.page_count]
    rh_sig = cfg.get("running_header_signature", [])
    skip_ratio = cfg.get("skip_large_ratio", 2.4)
    for page_idx in pages:
        page = doc[page_idx]
        for block in page.get_text("dict", sort=True)["blocks"]:
            if block.get("type") != 0: continue
            wr_pairs = set()
            text = ""
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    t = span["text"].strip()
                    if t:
                        ratio = size_bucket(span["size"]) / body_size
                        wr_pairs.add((font_weight(span["font"]), ratio))
                        text += span["text"]
            text = " ".join(text.split()).strip()
            if not text: continue
            if re.match(r"^\d{1,3}$", text):
                skip_set.add(normalise_key(text)); continue
            if any(r > skip_ratio for _, r in wr_pairs):
                skip_set.add(normalise_key(text)); continue
            if rh_sig and all(
                any(_match_rule(w, r, rule) for w, r in wr_pairs) for rule in rh_sig
            ):
                skip_set.add(normalise_key(text))
    return skip_set


def build_blockquote_set(pdf_path: Path, cfg: dict, body_size: float, page_range=None) -> tuple:
    import fitz
    bq_set = set()
    cit_set = set()
    doc = fitz.open(str(pdf_path))
    pages = range(doc.page_count) if page_range is None else [
        p for p in page_range if p < doc.page_count]
    max_ratio = cfg.get("quote_max_ratio", 0.88)
    cit_max = cfg.get("citation_max_chars", 80)
    for page_idx in pages:
        page = doc[page_idx]
        for block in page.get_text("dict", sort=True)["blocks"]:
            if block.get("type") != 0: continue
            font_chars: dict = {}
            text = ""
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    t = span["text"]
                    if t.strip():
                        key = (span["font"], size_bucket(span["size"]))
                        font_chars[key] = font_chars.get(key, 0) + len(t.strip())
                    text += t
            if not font_chars: continue
            _, dom_size = max(font_chars, key=font_chars.get)
            if dom_size / body_size > max_ratio: continue
            text = " ".join(text.split()).strip()
            if not text or not any(c.isalpha() for c in text): continue
            key = normalise_key(text[:60])
            if len(text) > cit_max: bq_set.add(key)
            else: cit_set.add(key)
    return bq_set, cit_set


def build_verse_map(pdf_path: Path, cfg: dict, body_size: float, page_range=None) -> dict:
    import fitz
    verse_map = {}
    doc = fitz.open(str(pdf_path))
    pages = range(doc.page_count) if page_range is None else [
        p for p in page_range if p < doc.page_count]
    sig = cfg.get("verse_label_signature", [])
    if not sig: return verse_map
    for page_idx in pages:
        page = doc[page_idx]
        for block in page.get_text("dict", sort=True)["blocks"]:
            if block.get("type") != 0: continue
            wr_pairs = set()
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    if span["text"].strip():
                        ratio = size_bucket(span["size"]) / body_size
                        wr_pairs.add((font_weight(span["font"]), ratio))
            if not all(any(_match_rule(w, r, rule) for w, r in wr_pairs) for rule in sig):
                continue
            lines_out = []
            verse_num = None
            for line in block.get("lines", []):
                line_text = "".join(s["text"] for s in line.get("spans", [])).strip()
                if not line_text: continue
                m = re.match(r"^VERSE\s*(\d+)\s*(.*)", line_text, re.IGNORECASE)
                if m and verse_num is None:
                    verse_num = m.group(1)
                    rest = m.group(2).strip()
                    if rest: lines_out.append(rest)
                elif verse_num is not None:
                    lines_out.append(line_text)
            if verse_num and lines_out and verse_num not in verse_map:
                verse_map[verse_num] = lines_out
    return verse_map


def dump_fonts(pdf_path: Path, page_range=None) -> None:
    import fitz
    doc = fitz.open(str(pdf_path))
    pages = range(doc.page_count) if page_range is None else [
        p for p in page_range if p < doc.page_count]
    freq: dict = {}
    samples: dict = {}
    for page_idx in pages:
        page = doc[page_idx]
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0: continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    t = span["text"].strip()
                    if any(c.isalpha() for c in t):
                        key = (span["font"], size_bucket(span["size"]))
                        freq[key] = freq.get(key, 0) + len(t)
                        if key not in samples: samples[key] = t[:50]
    body_font, body_size = max(freq, key=freq.get)
    print(f"\nBody font (most frequent): {body_font} @ {body_size}pt")
    print(f"\n{'Font':<40} {'Size':>6} {'Ratio':>6} {'Weight':>10} {'Chars':>8}  Sample")
    print("-" * 100)
    for (font, size), count in sorted(freq.items(), key=lambda x: -x[1]):
        ratio = size / body_size
        weight = font_weight(font)
        sample = samples.get((font, size), "")
        print(f"{font:<40} {size:>6.1f} {ratio:>6.2f} {weight:>10} {count:>8}  {sample}")
    print(f"\nTotal: {len(freq)} font+size combinations")
    print("Use these ratios to configure headings in pdf_config.yaml.")


# ---- Post-processing passes ----

def fix_headings(markdown: str, heading_map: dict, skip_set: set) -> str:
    lines = markdown.splitlines()
    out = []
    for line in lines:
        if normalise_key(re.sub(r"[#>]", "", line)) in skip_set: continue
        m = re.match(r'^(#{1,6})\s+(.+)$', line)
        if m:
            content = m.group(2)
            content_clean = re.sub(r'^\*\*(.+)\*\*$', r'\1', content.strip())
            content_clean = re.sub(r'^\*(.+)\*$', r'\1', content_clean.strip())
            clean = normalise_key(content_clean)
            if clean in skip_set: continue
            if clean in heading_map:
                out.append(f"{heading_map[clean]} {content_clean}")
            else:
                out.append(f"{m.group(1)} {content_clean}")
        else:
            stripped = line.strip()
            bm = re.match(r'^\*\*(.+?)\*\*$', stripped)
            if bm:
                inner = bm.group(1)
                clean = normalise_key(inner)
                if clean in heading_map:
                    out.append(f"{heading_map[clean]} {inner}")
                    continue
            body_clean = normalise_key(line)
            if body_clean in heading_map and line.strip() and len(line.strip()) > 2:
                out.append(f"{heading_map[body_clean]} {line.strip()}")
            else:
                out.append(line)
    return '\n'.join(out)


def fix_verse_labels(markdown: str, verse_map: dict) -> str:
    if not verse_map:
        return re.sub(
            r'^(?:#{1,6}\s+)?\*?\*?VERSE\s+(\d+)\*?\*?\s*$',
            lambda m: f"###### Verse {m.group(1)}",
            markdown, flags=re.MULTILINE | re.IGNORECASE)
    lines = markdown.splitlines()
    out = []
    i = 0
    used_nums: set = set()
    while i < len(lines):
        line = lines[i]
        m = re.match(r'^(?:#{1,6}\s+)?\*?\*?VERSE\s+(\d+)\*?\*?\s*$', line, re.IGNORECASE)
        if m:
            verse_num = m.group(1)
            out.append(f"###### Verse {verse_num}")
            if verse_num in verse_map and verse_num not in used_nums:
                out.append("")
                vlines = verse_map[verse_num]
                for j, vl in enumerate(vlines):
                    out.append(f"{vl}  " if j < len(vlines) - 1 else vl)
                out.append("")
                used_nums.add(verse_num)
                i += 1
                while i < len(lines):
                    nl = lines[i].strip()
                    if nl.startswith('#') or re.match(r'^\*?\*?VERSE\s+\d+', nl, re.IGNORECASE):
                        break
                    i += 1
                continue
            else:
                out.append("")
        else:
            out.append(line)
        i += 1
    return '\n'.join(out)


def fix_double_blockquote_citations(markdown: str) -> str:
    return re.sub(r'^> > (.+)$', r'<< \1', markdown, flags=re.MULTILINE)


def fix_blockquotes(markdown: str, bq_set: set, cit_set: set) -> str:
    lines = markdown.splitlines()
    out = []
    for line in lines:
        stripped = line.strip()
        if not stripped or line.startswith('>') or line.startswith('<<') or line.startswith('#'):
            out.append(line); continue
        key = normalise_key(stripped[:60])
        if key in bq_set: out.append(f"> {stripped}")
        elif key in cit_set: out.append(f"<< {stripped}")
        else: out.append(line)
    return '\n'.join(out)


def fix_citations(markdown: str, cfg: dict) -> str:
    patterns = cfg.get("_citation_res", [])
    cit_max = cfg.get("citation_max_chars", 80)
    lines = markdown.splitlines()
    out = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or stripped.startswith('>') \
                or stripped.startswith('<<') or stripped.startswith('-') \
                or stripped.startswith('*') or len(stripped) > 120:
            out.append(line); continue
        prev_blank = (i == 0) or (lines[i-1].strip() == '')
        next_blank = (i == len(lines)-1) or (lines[i+1].strip() == '')
        if not (prev_blank and next_blank):
            out.append(line); continue
        if any(p.match(stripped) for p in patterns):
            out.append(f"<< {stripped}"); continue
        prev_content = next(
            (lines[j].strip() for j in range(i-1, -1, -1) if lines[j].strip()), "")
        if (prev_content.startswith('>') or prev_content.startswith('<<')) and len(stripped) < cit_max:
            out.append(f"<< {stripped}"); continue
        out.append(line)
    return '\n'.join(out)


def fix_bullet_numbers(markdown: str) -> str:
    return re.sub(r'^- (\d+\.)\s', r'\1 ', markdown, flags=re.MULTILINE)


def fix_hyphenation(markdown: str) -> str:
    """Only merge when next non-blank line starts lowercase (mid-word)."""
    lines = markdown.splitlines()
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.rstrip().endswith('-') and len(line.strip()) > 5:
            j = i + 1
            while j < len(lines) and not lines[j].strip(): j += 1
            if j < len(lines):
                next_line = lines[j].lstrip()
                if next_line and next_line[0].islower() and not next_line.startswith('#'):
                    out.append(line.rstrip()[:-1] + lines[j].lstrip())
                    i = j + 1; continue
        out.append(line)
        i += 1
    return '\n'.join(out)


def fix_pullquote_fragments(markdown: str) -> str:
    lines = markdown.splitlines()
    out = []
    for line in lines:
        if line.startswith(' ') and len(line.strip()) < 120 and line.strip():
            s = line.strip()
            if not any(s.startswith(c) for c in ['-', '*', '#', '>']):
                continue
        out.append(line)
    return '\n'.join(out)


def fix_missing_section_headings(markdown: str, cfg: dict) -> str:
    insertions = cfg.get("missing_section_headings", [])
    if not insertions: return markdown
    italic_entries = [e for e in insertions if "italic_snippet" in e]
    before_entries = [e for e in insertions if "before_heading" in e]
    lines = markdown.splitlines()
    out = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        for entry in before_entries:
            target = entry["before_heading"].strip()
            if stripped == target:
                heading = entry["heading"]
                heading_text = re.sub(r'^#+\s+', '', heading).strip().lower()
                prev = '\n'.join(lines[max(0, i-6):i]).lower()
                if heading_text not in prev:
                    out.append("")
                    out.append(heading)
                    for extra in entry.get("insert_lines", []): out.append(extra)
                    if entry.get("insert_lines"): out.append("")
                break
        if stripped.startswith('*') and stripped.endswith('*') and len(stripped) > 30:
            text_lower = stripped.lower()
            for entry in italic_entries:
                if entry["italic_snippet"].lower() in text_lower:
                    heading = entry["heading"]
                    heading_text = re.sub(r'^#+\s+', '', heading).strip().lower()
                    prev = '\n'.join(lines[max(0, i-6):i]).lower()
                    if heading_text not in prev:
                        out.append("")
                        out.append(heading)
                    break
        out.append(line)
    return '\n'.join(out)


def fix_discussion_question_groups(markdown: str, cfg: dict) -> str:
    labels_cfg = cfg.get("discussion_question_labels", [
        "##### Searching the Text", "##### Seeking the Truth", "##### Evaluating Our Lives"])
    if not labels_cfg: return markdown
    markdown = re.sub(r'\n+\*\*[A-Z][A-Z\s]+\*\*\n+(?=\n*#{1,4}\s+Discussion)', '\n\n', markdown)
    lines = markdown.splitlines()
    out = []
    in_dq = False
    group_count = 0
    for line in lines:
        if re.match(r'^####\s+\*?\*?Discussion Questions\*?\*?', line, re.IGNORECASE):
            in_dq = True; group_count = 0; out.append(line); continue
        if in_dq and re.match(r'^#{1,4}\s+', line) and not re.match(r'^#{5,}', line):
            in_dq = False
        if in_dq and re.match(r'^1\.\s+', line) and group_count < len(labels_cfg):
            if group_count > 0: out.append('')
            out.append(labels_cfg[group_count]); out.append(''); group_count += 1
        out.append(line)
    return '\n'.join(out)


def fix_structural_labels(markdown: str) -> str:
    lines = markdown.splitlines()
    out = []
    for line in lines:
        s = line.strip()
        if re.match(r'^#{1,6}\s+[A-Z][A-Z\s]+$', s): continue
        if re.match(r'^\*\*[A-Z][A-Z\s]+\*\*$', s): continue
        if re.match(r'^<<\s+\*\*[A-Z\s]+\*\*$', s): continue
        if re.match(r'^\*\*[A-Z]\*\*$', s): continue
        if re.match(r'^\*".+\.\.\.\*$', s): continue
        if s == '\u2022': continue
        if re.match(r'^#{1,6}\s+\w.*:$', s):
            out.append(re.sub(r'^#{1,6}\s+', '', line)); continue
        if s.startswith('\u2022'):
            out.append(re.sub(r'^\u2022\s*', '- ', line)); continue
        out.append(line)
    return '\n'.join(out)


def fix_final_review_table(markdown: str, cfg: dict) -> str:
    """Convert single-column Marker tables to headed lists using config rules."""
    rules = cfg.get("table_to_list", [])
    if not rules: return markdown
    lines = markdown.splitlines()
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        matched_rule = None
        if line.strip().startswith('|') and i + 1 < len(lines) and '|---' in lines[i + 1]:
            for rule in rules:
                if rule["header_contains"] in line:
                    matched_rule = rule; break
        if matched_rule:
            out.append(matched_rule["output_heading"]); out.append("")
            i += 2
            while i < len(lines) and lines[i].strip().startswith('|'):
                cell = lines[i].strip().strip('|').strip()
                if cell and not cell.startswith('---'):
                    text = re.sub(r'<br\s*/?>', ' ', cell).strip()
                    m2 = re.match(r'^(\d+)\.\s+(.+)', text)
                    if m2: out.append(f"{m2.group(1)}. {m2.group(2)}")
                i += 1
            out.append(""); continue
        out.append(line); i += 1
    return '\n'.join(out)


def fix_junk_content(markdown: str, cfg: dict) -> str:
    """Remove non-content text using config-driven patterns."""
    line_pats = [re.compile(p) for p in cfg.get("skip_line_patterns", [])]
    table_markers = cfg.get("skip_table_markers", [])
    lines = markdown.splitlines()
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if any(p.match(stripped) for p in line_pats): i += 1; continue
        if stripped.startswith('|') and any(m in stripped for m in table_markers):
            while i < len(lines) and lines[i].strip().startswith('|'): i += 1
            continue
        out.append(line); i += 1
    return '\n'.join(out)


def post_process(markdown: str, heading_map: dict, skip_set: set,
                 bq_set: set, cit_set: set, verse_map: dict, cfg: dict) -> str:
    markdown = markdown.replace('\r\n', '\n').replace('\r', '\n')
    markdown = re.sub(r'^!\[.*?\]\(.*?\)\s*$', '', markdown, flags=re.MULTILINE)
    markdown = re.sub(r'^-{20,}\s*$', '', markdown, flags=re.MULTILINE)
    markdown = fix_pullquote_fragments(markdown)
    markdown = fix_headings(markdown, heading_map, skip_set)
    markdown = fix_verse_labels(markdown, verse_map)
    markdown = fix_double_blockquote_citations(markdown)
    markdown = fix_blockquotes(markdown, bq_set, cit_set)
    markdown = fix_citations(markdown, cfg)
    markdown = fix_bullet_numbers(markdown)
    markdown = fix_hyphenation(markdown)
    markdown = fix_final_review_table(markdown, cfg)
    markdown = fix_junk_content(markdown, cfg)
    markdown = fix_missing_section_headings(markdown, cfg)
    markdown = fix_discussion_question_groups(markdown, cfg)
    markdown = fix_structural_labels(markdown)
    markdown = re.sub(r'\n{3,}', '\n\n', markdown)
    return markdown.strip() + '\n'


# ---- Marker bug patch ----

def patch_block_relabel():
    from copy import deepcopy
    from marker.processors.block_relabel import BlockRelabelProcessor
    from marker.schema.registry import get_block_class
    def patched_call(self, document):
        if len(self.block_relabel_map) == 0: return
        for page in document.pages:
            for block in page.structure_blocks(document):
                if block.block_type not in self.block_relabel_map: continue
                confidence_thresh, relabel_block_type = self.block_relabel_map[block.block_type]
                confidence = block.top_k.get(block.block_type)
                if confidence is None: continue
                if confidence > confidence_thresh: continue
                new_block_cls = get_block_class(relabel_block_type)
                new_block = new_block_cls(
                    polygon=deepcopy(block.polygon), page_id=block.page_id,
                    structure=deepcopy(block.structure),
                    text_extraction_method=block.text_extraction_method,
                    source="heuristics", top_k=block.top_k, metadata=block.metadata)
                page.replace_block(block, new_block)
    BlockRelabelProcessor.__call__ = patched_call


def get_available_gemini_model(api_key: str) -> str:
    candidates = ["gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-1.5-flash", "gemini-1.5-pro"]
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        available = {m.name.split("/")[-1] for m in client.models.list()}
        for c in candidates:
            if c in available: return c
    except Exception:
        pass
    return "gemini-2.0-flash"


# ---- Main ----

def main():
    parser = argparse.ArgumentParser(description="Convert PDF to Markdown using Marker + font-based post-processing.")
    parser.add_argument("input", help="Path to PDF, OR raw Marker .md file (with --postprocess)")
    parser.add_argument("pdf", nargs="?", help="PDF path (required with --postprocess)")
    parser.add_argument("output", nargs="?", help="Output .md path (optional)")
    parser.add_argument("--template", default="homestead")
    parser.add_argument("--page-range", default="", help="0-indexed page range e.g. '62-200'")
    parser.add_argument("--dump-fonts", action="store_true")
    parser.add_argument("--save-raw", action="store_true")
    parser.add_argument("--postprocess", action="store_true",
                        help="Skip Marker; apply post-processing to an existing raw .md file.")
    args = parser.parse_args()

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

    if args.dump_fonts:
        pdf_path = Path(args.input)
        if not pdf_path.exists(): print(f"ERROR: File not found: {pdf_path}"); sys.exit(1)
        dump_fonts(pdf_path, page_range); return

    cfg = load_template(args.template)
    print(f"Template: {args.template}")

    if args.postprocess:
        raw_md_path = Path(args.input)
        if not raw_md_path.exists(): print(f"ERROR: Raw markdown not found: {raw_md_path}"); sys.exit(1)
        if not args.pdf: print("ERROR: --postprocess requires PDF path as second arg"); sys.exit(1)
        pdf_path = Path(args.pdf)
        if not pdf_path.exists(): print(f"ERROR: PDF not found: {pdf_path}"); sys.exit(1)
        output_path = Path(args.output) if args.output else raw_md_path.with_suffix(".md")
        if output_path == raw_md_path:
            output_path = raw_md_path.with_stem(raw_md_path.stem + "_processed")
        body_font_name, body_size = detect_body_font(pdf_path, page_range)
        print(f"Body font (auto): {body_font_name} @ {body_size}pt")
        print("Building font maps from PDF...")
        heading_map = build_heading_map(pdf_path, cfg, body_size, page_range)
        skip_set = build_skip_set(pdf_path, cfg, body_size, page_range)
        bq_set, cit_set = build_blockquote_set(pdf_path, cfg, body_size, page_range)
        verse_map = build_verse_map(pdf_path, cfg, body_size, page_range)
        print(f"  {len(heading_map)} headings, {len(skip_set)} skips, "
              f"{len(bq_set)} blockquotes, {len(cit_set)} citations, {len(verse_map)} verses.")
        raw_markdown = raw_md_path.read_text(encoding="utf-8")
        print("Post-processing...")
        markdown = post_process(raw_markdown, heading_map, skip_set, bq_set, cit_set, verse_map, cfg)
        output_path.write_text(markdown, encoding="utf-8")
        print(f"Done! Written to: {output_path} ({len(markdown.splitlines())} lines)")
        return

    # Full conversion mode
    pdf_path = Path(args.input)
    if not pdf_path.exists(): print(f"ERROR: File not found: {pdf_path}"); sys.exit(1)
    output_path = Path(args.output) if args.output else pdf_path.with_suffix(".md")
    body_font_name, body_size = detect_body_font(pdf_path, page_range)
    print(f"Body font (auto): {body_font_name} @ {body_size}pt")
    print("Building font maps from PDF...")
    heading_map = build_heading_map(pdf_path, cfg, body_size, page_range)
    skip_set = build_skip_set(pdf_path, cfg, body_size, page_range)
    bq_set, cit_set = build_blockquote_set(pdf_path, cfg, body_size, page_range)
    verse_map = build_verse_map(pdf_path, cfg, body_size, page_range)
    print(f"  {len(heading_map)} headings, {len(skip_set)} skips, "
          f"{len(bq_set)} blockquotes, {len(cit_set)} citations, {len(verse_map)} verses found.")

    google_api_key = os.environ.get("GOOGLE_API_KEY", "")
    use_llm = bool(google_api_key)
    if use_llm: print("GOOGLE_API_KEY found -- LLM heading correction enabled.")
    else: print("No GOOGLE_API_KEY -- font-based heading correction only.")

    patch_block_relabel()

    print("Loading models (~30s from disk)...")
    import torch
    from marker.models import create_model_dict
    models = create_model_dict(device="cpu", dtype=torch.float32)
    print("Models loaded.")

    marker_config = {
        "lowres_image_dpi": 96,
        "block_relabel_str": "SectionHeader:Text:0.6,Figure:Text:1.0,Picture:Text:1.0",
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
        "disable_image_extraction": True,
        "extract_images": False,
    }

    processor_list = None  # Use Marker's full default processor list

    llm_service_cls = None
    if use_llm:
        model_name = get_available_gemini_model(google_api_key)
        marker_config["gemini_api_key"] = google_api_key
        marker_config["gemini_model_name"] = model_name
        llm_service_cls = "marker.services.gemini.GoogleGeminiService"
        print(f"LLM enabled (model: {model_name}).")

    if page_range:
        marker_config["page_range"] = page_range

    from marker.converters.pdf import PdfConverter
    print(f"Converting {pdf_path.name}...")
    converter = PdfConverter(
        artifact_dict=models, processor_list=processor_list,
        config=marker_config, llm_service=llm_service_cls)
    rendered = converter(str(pdf_path))

    if args.save_raw:
        raw_path = output_path.with_suffix(".raw.md")
        raw_path.write_text(rendered.markdown, encoding="utf-8")
        print(f"Raw Marker output saved: {raw_path}")

    print("Post-processing...")
    markdown = post_process(
        rendered.markdown, heading_map, skip_set, bq_set, cit_set, verse_map, cfg)
    output_path.write_text(markdown, encoding="utf-8")
    print(f"Done! Written to: {output_path} ({len(markdown.splitlines())} lines)")


if __name__ == "__main__":
    main()
