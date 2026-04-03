# Architecture & Technical Reference

This document captures the design decisions, technical learnings, and implementation patterns for the Affinity-to-Markdown conversion system. It exists so future development (by humans or Claude) can build on prior work without re-discovering the same things.

**Last updated:** April 3, 2026

---

## System Overview

Two independent Cloud Run services, each with its own deploy workflow:

| Service | Cloud Run Name | Source | Memory | Purpose |
|---------|---------------|--------|--------|---------|
| AFPUB Converter | `afpub-converter` | repo root | 2 GB | Converts `.afpub` binary files → Markdown using a custom binary parser |
| Marker PDF Converter | `marker-pdf-converter` | `marker-pdf/` | 8 GB | Converts `.pdf` files → Markdown using the Marker ML library |

Active development is on the **Marker PDF** path. The AFPUB converter is a stable fallback.

**Local CLI** is the primary development workflow. Cloud Run deployment is secondary.

---

## Active Files

| File | Lines | Purpose |
|------|-------|---------|
| `marker-pdf/run.py` | ~1100 | Main converter + full post-processing pipeline |
| `marker-pdf/templates/homestead/pdf_config.yaml` | ~199 | All book-specific configuration |

**IMPORTANT:** `run.py` is ~54KB. It exceeds what GitHub MCP tools can push inline. For future changes, either use `str_replace` on the git copy for small edits, or have Steve download the file and push locally.

---

## Conversion Pipeline Overview

```
PDF file
  → Marker (ML-based extraction) → raw Markdown
  → PyMuPDF font scanning → heading_map, heading_order, skip_set, etc.
  → post_process() pipeline (25+ passes) → clean Markdown
  → fix_front_matter() → title/copyright page corrections
  → fix_heading_hierarchy() → semantic heading restructuring (Phases 1-4)
  → final output
```

### Usage

```bash
# Full conversion (Marker + post-processing)
python run.py "path/to/book.pdf"

# Post-processing only (fast iteration, ~5 seconds)
python run.py "path/to/raw.md" "path/to/book.pdf" --postprocess

# Font analysis
python run.py "path/to/book.pdf" --dump-fonts
```

---

## Design Principles

1. **All content-specific configuration lives in YAML** — session names, part labels, subdivision labels, front matter corrections. The code in `run.py` is generic.
2. **Font ratios, not absolute sizes** — all heading detection uses ratios relative to the auto-detected body font size, making it portable across PDFs.
3. **heading_map from PyMuPDF is the source of truth** — Marker's ML-based heading detection is unreliable. We override it entirely with font-based analysis.
4. **heading_order provides document-order context** — sequential matching ensures headings are assigned correctly even when the same text appears multiple times.
5. **fix_heading_hierarchy runs LAST** — it restructures the final output after all other passes have stabilized the content.
6. **OCR is OFF** (`disable_ocr: True`) — all text is vector from Affinity Publisher.

---

## PyMuPDF Font Scanning Functions

These run on the PDF before post-processing and build lookup tables:

| Function | Returns | Purpose |
|----------|---------|---------|
| `detect_body_font()` | font name, size | Auto-detects the most common font as body text baseline |
| `build_heading_map()` | dict + ordered list | Maps normalised heading text → markdown levels using font ratios |
| `build_skip_set()` | set | Running headers, page numbers, oversized decorative text to remove |
| `build_blockquote_set()` | bq set, citation set | Small-font text: long blocks → blockquotes, short → citations |
| `build_verse_map()` | dict | Multi-line verse label content (VERSE 1 with its text) |
| `build_callout_set()` | list | Large-font standalone text for `<Callout>` tags |
| `build_inline_bold_set()` | list | Bold phrases within mixed-weight body paragraphs |
| `build_rotated_subdivisions()` | list of (label, anchor_key, page) | Vertical sidebar text (14pt bold) matched to horizontal anchors |

---

## Post-Processing Pipeline (`post_process()`)

Passes run in this order:

1. `fix_pullquote_fragments` — remove indented orphan text
2. `fix_headings` — reassign heading levels from heading_map using heading_order for sequential matching
3. `fix_verse_labels` — normalize VERSE N labels, inject verse text from verse_map
4. `fix_double_blockquote_citations` — convert `> >` to `<<`
5. `fix_blockquotes` — apply blockquote formatting from bq_set
6. `fix_citations` — apply citation formatting from citation patterns + proximity
7. `fix_bullet_numbers` — convert `- 1.` to `1.`
8. `fix_hyphenation` — rejoin hyphenated words split across lines
9. `fix_callouts` — wrap callout text in `<Callout>` tags, remove duplicates
10. `fix_empty_tables` — remove tables that are mostly empty cells
11. `fix_toc_tables` — remove table-of-contents tables (detected by page number columns)
12. `fix_final_review_table` — convert specific tables to numbered lists
13. `fix_inline_bold` — restore bold phrases in list items
14. `fix_junk_content` — remove lines matching skip_line_patterns
15. `fix_artwork_images` — detect art citations, insert `![title](filename)` references
16. `fix_missing_headings` — insert headings that are in heading_order but missing from output
17. `fix_dedup_headings` — remove consecutive duplicate headings
18. `fix_heading_fragments` — remove orphan text fragments near H1 headings
19. `fix_missing_section_headings` — insert section headings from config
20. `fix_discussion_question_groups` — insert sub-labels (Searching the Text, etc.)
21. `fix_structural_labels` — remove ALL-CAPS structural labels, convert bullets
22. `fix_bold_bullets` — convert `**• text**` to `- **text**`
23. `fix_front_matter` — config-driven title/copyright page corrections
24. `fix_heading_hierarchy` — the big one: restructure to semantic hierarchy (see below)

---

## Heading Hierarchy Restructuring (`fix_heading_hierarchy`)

This is the most complex pass. It transforms font-based heading levels (H1-H6) into semantic levels matching the book's structure.

### Phase 1: Session Structure
- Finds H1/H2 pairs in the output (e.g., `# Under God's Fatherly Care` + `## Building a Home Devoted to God`)
- Merges them into combined H4 titles: `#### Under God's Fatherly Care: Building a Home Devoted to God`
- Inserts Part headings (H1): `# PART ONE: Preparation`
- Inserts Session headings (H2): `## Session One`
- Maps from `session_map` config (17 entries, document order)

### Phase 2: Level Shifts
- H3 → H4, H4 → H5, H5 → H6 (shift everything down one)
- H6 → bold text (verses become `**Verse 1**`)
- H2 (standalone) → H4

### Phase 3: Heading-Order Subdivisions
- Inserts H3 sub-divisions like `### Session 1 Community Study`
- Uses `heading_order` from PyMuPDF to find decorative H1-level text (Community Study, Weekly Disciplines, Reflective Projects) between sessions
- Matches each subdivision to its session using a counter that tracks known H1 title keys
- Produces 20 H3s (Introduction + 6 sessions × 3 subdivisions + Review)

### Phase 3b: Rotated Sidebar Subdivisions
- `build_rotated_subdivisions()` scans PDF for vertical text (`dir != (1,0)`) at 14pt bold
- Matches each label to the first horizontal heading on the same page (the anchor)
- Labels listed in config `rotated_subdivision_labels` (18 entries)
- Smart apostrophe normalization for matching (PDF curly quotes vs config straight quotes)
- **Boundary check:** skips anchor matches where a matching-name H2 follows within 8 lines (prevents H3 appearing before its H2 container in Part Three)
- Produces 18 H3s (Day One/Two, 7 Outdoor Experiences, 6 Mentoring Sessions, General Reflections, Personal Testimony, Community Confession, Celebration Ceremony)

### Phase 3c: Config-Driven Overrides
- `subdivision_overrides` config for headings not auto-detected
- Each override specifies: session name, label to insert, and the H4 heading to insert before
- Currently handles: Conclusion Community Study, Introduction Orientation and Overview
- Produces 2 H3s

### Phase 4: Cleanup
- Removes plain text subdivision labels that now duplicate H3 headings
- Removes misplaced H5 headings that appear just before their H2 container
- Removes first of duplicate adjacent H4 headings
- Removes artifact headings listed in `remove_artifact_headings` config

---

## Front Matter Corrections (`fix_front_matter`)

Config-driven fixes for title page and copyright page formatting issues:

- **Runs before heading hierarchy** (after all other passes)
- **Boundary:** only applies to lines before `ends_before` marker (e.g., `## Series' Preface`)
- **remove_lines:** regex patterns for lines to delete entirely (e.g., fill-in blanks)
- **text_replacements:** exact-line and starts-with matching to:
  - Split merged title text to multi-line
  - Split merged author names to separate bold lines
  - Strip erroneous `<<` and `>` markers from copyright page text
- **Does NOT affect:** bullet lists, italic text, or epigraph blockquotes (matching is precise)

---

## Config Structure (`pdf_config.yaml`)

```yaml
# Font detection
body_font: auto
headings: [{weight, min_ratio, max_ratio, level}, ...]
skip_large_ratio: 2.4
running_header_signature: [...]

# Text detection
quote_max_ratio: 0.88
citation_max_chars: 80
verse_label_signature: [...]
callout_signature: [...]
citation_patterns: [regex, ...]
discussion_question_labels: [...]

# Content cleanup
skip_line_patterns: [regex, ...]
skip_table_markers: [...]
table_to_list: [{header_contains, output_heading}, ...]

# Front matter
front_matter_corrections:
  ends_before: "## Series' Preface"
  remove_lines: [regex, ...]
  text_replacements: [{match, replace}, ...]

# Heading hierarchy (the big config section)
heading_hierarchy:
  front_matter_label: "Front Matter"
  parts: [{label, before_session, marker}, ...]
  session_map: [session_name_or_null, ...]  # 17 entries
  trailing_section: {part_label, session_name, subtitle_contains}
  subdivision_labels: [...]      # 3: Community Study, Weekly Disciplines, Reflective Projects
  rotated_subdivision_labels: [...]  # 18 sidebar labels
  subdivision_overrides: [{session, label, before_heading}, ...]  # 2 manual overrides
  heading_text_fixes: [{match, replace}, ...]
  remove_artifact_headings: [...]
```

---

## Current Output Stats (Homestead full book, 481 pages)

| Metric | Count |
|--------|-------|
| Lines | ~4860 |
| H1 (Parts) | 5 |
| H2 (Sessions) | 17 |
| H3 (Sub-divisions) | 40 |
| H4 (Section headings) | 117 |
| H5 (Sub-sections) | 373 |
| H6 (Sub-sub-sections) | 119 |
| Bold verses | 33 |
| Callouts | 62 |
| Images | 12 |

---

## Known Remaining Issues

- Some H3 sub-divisions in Part Three (Personal Testimony, Community Confession, Celebration Ceremony) appear after the Overview content rather than right after H2 — minor structural positioning
- `###### Conclusion` at end of Part One appears just before `## Conclusion` — misplaced H6
- `<< for` orphan line in front matter dedication page
- Some front matter epigraph quotes may need additional formatting review

---

## Homestead Book PDF — Font Analysis

Body font: `TimesNewRomanPSMT @ 10.0pt`

| Font Weight | Size (pt) | Ratio | Config Level | Semantic Role |
|-------------|-----------|-------|--------------|---------------|
| regular | 20.0 | 2.0 | 1 | Session title (H1 → merged to H4) |
| bold | 20.0 | 2.0 | 3 | Movement title (→ H4) |
| italic | 14.0 | 1.4 | 2 | Session subtitle (H2 → merged with H1) |
| bold | 18.0 | 1.8 | 4 | Special heading |
| bold | 14.0 | 1.4 | 4 | Section heading |
| bold | 12.0 | 1.2 | 5 | Sub-section heading |
| regular | 10.0 | 1.0 | — | Body text |
| regular | 8.0 | 0.8 | — | Blockquote/citation text |

---

## Infrastructure Notes

- **Cloud Run deployment:** GCP project `affinity-markdown-converter`, managed via `@google-cloud/cloud-run-mcp` in Claude Desktop
- **Models:** ~6-8 GB RAM, 5 Surya ML models, loaded synchronously before uvicorn starts
- **Base Docker image:** bakes models into `marker-pdf-base:latest`, app image just copies code
- **Local Python:** 3.11 venv at `C:\Users\Steve\Affinity-to-Markdown\marker-pdf\venv311`
- **GitHub:** `Noble-Collective/Affinity-to-Markdown`, `main` branch

---

## Development Workflow

1. Claude makes changes to `run.py` and `pdf_config.yaml` in its sandbox
2. Tests against the full 481-page PDF with regression checks
3. For config changes: pushes via GitHub MCP API
4. For run.py changes: **must provide as download** for Steve to push locally (file too large for API)
5. Steve runs `git pull`, then `python run.py raw.md book.pdf --postprocess`
6. Steve uploads output `.md` back to Claude for review
7. Prefer small incremental changes with check-ins over large autonomous runs

---

## Session Log

| Date | What was done |
|------|--------------|
| Mar 2026 | AFPUB binary parser v0.10, switched to PDF extraction, evaluated Marker |
| Mar 2026 | Marker infrastructure: base image, synchronous loading, Cloud Run deploy |
| Mar 2026 | Font analysis, config iterations 1-3, local CLI workflow established |
| Apr 3 2026 | **Post-processing pipeline built:** 25+ passes covering headings, blockquotes, citations, verses, callouts, images, tables, discussion questions, structural cleanup |
| Apr 3 2026 | **Heading hierarchy restructuring:** Phases 1-4, session/part structure, subdivision insertion from heading_order |
| Apr 3 2026 | **Rotated sidebar detection:** build_rotated_subdivisions() for vertical 14pt bold text, 18 H3s added |
| Apr 3 2026 | **Phase 3b boundary fix:** H3s for Part Three sessions no longer appear before their H2 containers |
| Apr 3 2026 | **Phase 3c overrides:** Conclusion Community Study + Introduction Orientation and Overview added |
| Apr 3 2026 | **Front matter corrections:** fix_front_matter() for title/copyright page formatting (remove fill-in line, split titles/authors, strip erroneous blockquote markers) |
| Apr 3 2026 | **Final stats:** H1=5, H2=17, H3=40, H4=117, H5=373, H6=119, 33 verses, 62 callouts, 12 images |
