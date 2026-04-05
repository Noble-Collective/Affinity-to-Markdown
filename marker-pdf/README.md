# marker-pdf — PDF to Markdown Converter

Converts Noble Collective book PDFs to clean Markdown using [Marker](https://github.com/datalab-to/marker) (ML-based extraction) + PyMuPDF (font-based post-processing).

---

## Quick Start

```bash
cd marker-pdf
source venv311/Scripts/activate   # Windows Git Bash (Python 3.11 venv)

# Full conversion (Marker + post-processing, ~10-15 min per session on CPU)
python run.py "path/to/book.pdf" --save-raw --template homestead

# Fast iteration: re-run post-processing only (seconds, not minutes)
python run.py raw.md book.pdf --postprocess

# Font calibration for a new book
python run.py "path/to/book.pdf" --dump-fonts

# Page range (useful for testing a single session)
python run.py "path/to/book.pdf" --save-raw --page-range 37-84
```

**Requirements:** Python 3.11, `pip install pyyaml pymupdf marker-pdf` in venv311.

---

## Architecture

Two-layer pipeline: Marker handles paragraph joining, list detection, and layout; PyMuPDF provides the font-level truth that corrects Marker's mistakes.

```
PDF
 │
 ▼
[1] PyMuPDF font scan
    ├── Body font auto-detection (most frequent font = body)
    ├── heading_map: {text: [level, ...]} from font ratio rules
    ├── heading_order: [(text, level), ...] in document order
    ├── skip_set: running headers, page numbers, decorative text
    ├── bq_set / cit_set: blockquote/citation text (small font)
    ├── verse_map: hymn verse text with proper line breaks
    ├── callout_texts: pull-quote text from callout font signature
    ├── inline_bold: bold phrases from mixed-weight body blocks
    ├── verse_sup: small bold text for verse number superscripts
    ├── right_aligned_map: short right-aligned text (citations)
    └── rotated_subdivisions: rotated sidebar heading labels
 │
 ▼
[2] Marker (ML)
    ├── Layout detection (surya model, ~6 min on CPU)
    ├── Text extraction (pdftext)
    ├── Paragraph joining, list detection, blockquote detection
    └── Figure/Picture → Text reclassification (patched)
 │
 ▼  raw.md  (Marker's output, saved with --save-raw)
 │
 ▼
[3] Post-processing pipeline (font-data-driven, 30+ passes)
    ├── Correct heading levels using heading_map
    ├── Restructure heading hierarchy (Parts, Sessions, subdivisions)
    ├── Insert missing headings from heading_order
    ├── Fix blockquotes, citations, verse labels
    ├── Rejoin text split at page boundaries (fix_page_breaks)
    ├── Restore inline bold, callouts
    ├── Convert artwork references to image tags
    ├── Remove empty tables, decorative content
    └── Structural cleanup + final normalization
 │
 ▼  output.md
```

### Design Principles

- **Font data is the source of truth.** The heading_map built from PyMuPDF font analysis determines what IS a heading and at what level. Marker's heading assignments are corrected or overridden by this data.
- **All fixes are content-agnostic.** Post-processing rules operate on font weight, size ratios, and structural patterns — never on specific text content. If the PDF content changed (e.g. misspelling a heading), the pipeline would still work because it keys on font properties, not text strings.
- **Text is a bridge, not a target.** Text strings from the PDF connect PyMuPDF's font data to Marker's text output (matching by normalized key). The text itself is not used for formatting decisions.
- **Content-specific entries belong in template config only.** The code (`run.py`) is generic across all books. Template-specific data (font ratios, discussion labels, skip patterns) lives in `pdf_config.yaml`.
- **Diagnose first, fix second.** When an output issue is reported, trace through raw Marker output, PyMuPDF font/position data, and pipeline passes to identify the root cause. Design rule-level fixes based on PDF properties (font, size, ratio, position). Never jump to text-specific config fixes without exhausting rule-based options first.
- **Fix the source when possible.** If Affinity exports a text block as an image (non-selectable text in the PDF), the best fix is to change the Affinity source — not to add OCR or config workarounds.

---

## Files

| File | Purpose |
|------|---------|
| `run.py` | Generic local runner — all conversion and post-processing logic |
| `templates/homestead/pdf_config.yaml` | Homestead book config (font ratios, headings, hierarchy, etc.) |
| `testing/extract_pdf_data.py` | Extracts PyMuPDF font data to JSON for offline pipeline testing |
| `app.py` | Cloud Run FastAPI server (separate from local runner) |
| `Dockerfile` | Cloud Run image (uses pre-built base) |
| `Dockerfile.base` | One-time base image build (includes model downloads) |
| `cloudbuild-base.yaml` | Cloud Build config for base image |

---

## Template System

All book-specific configuration lives in `templates/<n>/pdf_config.yaml`. The runner is fully generic — no font names, absolute sizes, or text content are hardcoded in `run.py`.

### Adding a new book

```bash
# 1. Dump font analysis
python run.py newbook.pdf --dump-fonts

# 2. Create templates/newbook/pdf_config.yaml
# 3. Set heading ratios to match the font table
# 4. Run with --template newbook
python run.py newbook.pdf --template newbook --save-raw
```

### pdf_config.yaml keys

```yaml
body_font: auto          # "auto" = most frequent font

headings:                # Rules matched top-to-bottom; first match wins
  - weight: bold         # regular | bold | italic | bold-italic
    min_ratio: 1.85      # font_size / body_font_size
    max_ratio: 2.15
    level: 3             # Markdown heading level (1-6)

skip_large_ratio: 2.4    # Blocks with ratio > this = decorative, skip

running_header_signature:    # Block must match ALL entries to be a running header
  - weight: bold
    min_ratio: 1.35
    max_ratio: 1.55

quote_max_ratio: 0.88    # Dominant font ratio <= this = quote/citation text
citation_max_chars: 80   # Short quote blocks → <<, long → >

verse_label_signature:   # Block must match ALL entries to be a verse label block
  - weight: bold
    min_ratio: 0.95
    max_ratio: 1.05

callout_signature:       # Font signature for magazine-style pull quotes
  - weight: regular
    min_ratio: 1.55
    max_ratio: 1.65

citation_patterns:       # Python regex; standalone short lines matching these → <<
  - '^[A-Z][a-zA-Z]+\s+\d+:\d+...$'

discussion_question_labels:  # Inserted before each group of questions (by 1. restart)
  - "##### Searching the Text"
  - "##### Seeking the Truth"
  - "##### Evaluating Our Lives"

discussion_heading_pattern: "Discussion Questions"  # H4 that triggers group insertion

skip_line_patterns:      # Lines matching these regexes are removed
  - '^Session \d+ (Community Study|Weekly Disciplines)'

skip_table_markers:      # Tables containing these strings are removed entirely
  - 'SEARCHING'

table_to_list:           # Convert specific tables to headed lists
  - header_contains: "Final Review"
    output_heading: "#### Final Review"

front_matter_corrections:    # Fixes for title/copyright pages
  ends_before: "## Series' Preface"
  remove_lines: ['^pattern$']
  text_replacements:
    - match: "old text"
      replace: "new text"

heading_hierarchy:       # Semantic heading restructuring (see section below)
  front_matter_label: "Front Matter"
  session_map: [null, "Session One", "Session Two", ...]
  parts:
    - before_session: "Session One"
      label: "PART ONE: Foundations"
      marker: "PART"
  trailing_section: { session_name: "Conclusion", ... }
  subdivision_labels: ["Community Study", "Weekly Disciplines", ...]
  rotated_subdivision_labels: ["Community Study", ...]
  subdivision_overrides: [{ session: "...", before_heading: "...", label: "..." }]
  heading_text_fixes: [{ match: "...", replace: "..." }]
  remove_artifact_headings: ["..."]
```

---

## Post-Processing Pipeline

Applied in order inside `post_process()`. Passes are grouped by function.

### Early cleanup

| # | Pass | What it does |
|---|------|-------------|
| 1 | Image/rule strip | Remove Marker image tags and horizontal rules |
| 2 | `fix_pullquote_fragments` | Remove indented margin pull-quotes. Must run before blockquotes |
| 3 | `fix_headings` | Remap heading levels using font-derived heading_map. Demotes non-mapped headings |

### Verse & blockquote correction

| # | Pass | What it does |
|---|------|-------------|
| 4 | `fix_verse_labels` | Replace `VERSE N` with `###### Verse N` + verse text from PyMuPDF |
| 5 | `fix_double_blockquote_citations` | Convert `> > Citation` → `<< Citation` |
| 6 | `fix_blockquotes` | Body text matching bq_set → `>`, cit_set → `<<`. Right-aligned body text → `<<` |
| 7 | Decorative pull-quote removal | Strip `> *...text"*` italic excerpt lines from verse collections |
| 8 | `fix_blockquote_continuations` | Rejoin italic scripture blockquotes split at page boundaries (add `>` prefix) |
| 9 | `fix_citations` | Standalone short paragraphs matching citation_patterns → `<<` |

### Text repair

| # | Pass | What it does |
|---|------|-------------|
| 10 | `fix_bullet_numbers` | Fix Marker bug: `- 1. Text` → `1. Text` |
| 11 | `fix_hyphenation` | Merge column-break hyphenated words |

### Table & content cleanup

| # | Pass | What it does |
|---|------|-------------|
| 12 | `fix_empty_tables` | Remove tables where >70% of cells are empty |
| 13 | `fix_toc_tables` | Remove tables where >80% of rows have page numbers in last cell |
| 14 | `fix_final_review_table` | Convert specific tables to headed numbered lists (config-driven) |
| 15 | `fix_inline_bold` | Restore inline bold in list items using font-derived bold phrase set |
| 16 | `fix_junk_content` | Remove lines/tables matching config skip patterns |
| 17 | `fix_artwork_images` | Convert artwork attribution lines to `![Title](filename)` image tags |

### Heading structure

| # | Pass | What it does |
|---|------|-------------|
| 18 | `fix_missing_headings` | Compare PDF heading_order against output, insert dropped headings |
| 19 | `fix_dedup_headings` | Remove duplicate adjacent headings |
| 20 | `fix_heading_fragments` | Remove orphan H1 fragments that are substrings of nearby H2+ headings |
| 21 | `fix_missing_section_headings` | Config-based fallback for headings not auto-detected |
| 22 | `fix_discussion_question_groups` | Insert group labels before question sets (detected by 1. restart) |

### Structural cleanup

| # | Pass | What it does |
|---|------|-------------|
| 23 | `fix_structural_labels` | Remove ALL-CAPS labels, single-char bold, bullet chars. Demote headings ending `:` |
| 24 | `fix_bold_bullets` | Convert `**• Text**:` → `- **Text**:` |
| 25 | Citation bold strip | Remove bold from `<< **text**` citation lines |
| 26 | `fix_front_matter` | Config-driven line removal and text replacement for title/copyright pages |

### Heading hierarchy (semantic restructuring)

| # | Pass | What it does |
|---|------|-------------|
| 27 | `fix_heading_hierarchy` | Major restructuring: merge H1+H2 into session titles, insert Part/Session/subdivision headings, shift H3-H5 down one level, convert H6 to bold, split H6+body merges (see section below) |

### Callouts & page breaks

| # | Pass | What it does |
|---|------|-------------|
| 28 | `fix_callouts` | Two-pass: Phase 1 removes standalone callout lines (including blockquote-wrapped). Phase 2 tags inline matches with `<Callout>` across paragraph groups |
| 29 | Callout adjacency merge | Merge `</Callout> <Callout>` into single span |
| 30 | `fix_page_breaks` | Rejoin text split mid-sentence at PDF page boundaries (see section below) |

### Final normalization

| # | Pass | What it does |
|---|------|-------------|
| 31 | Verse superscript conversion | Convert bold verse numbers (`**103:1**`) to `<sup>103:1</sup>` |
| 32 | Bold verse spacing | Remove extra blank after `**Verse N**` lines |
| 33 | Triple-blank collapse | `\n{3,}` → `\n\n` |

---

## Heading Hierarchy System

`fix_heading_hierarchy` restructures the flat font-based heading levels into a semantic document hierarchy with Parts, Sessions, and subdivisions. This is the most complex post-processing pass.

### Phase 1: Session structure
Walks the H1 headings and matches them to `session_map` entries. For each session:
- Inserts `# PART` headings before designated sessions
- Inserts `## Session Name` headings
- Merges H1 (title) + H2 (subtitle) into `#### Title: Subtitle`

### Phase 2: Level shifts
For all remaining headings not consumed by Phase 1:
- H6 → `**bold text**` (verse labels, minor headings)
- H3-H5 → shift down one level (H3→H4, H4→H5, H5→H6)
- H2 → `####` (standalone subtitles)

### Phase 2b: PART heading repositioning
Marker places Part intro paragraphs before the H1, but Phase 2 inserts `# PART` right before the H1. Fix: scan backward from each `# PART`, relocate long body paragraphs to after the PART+Session block.

### Phase 2c: H6+body split
Marker sometimes puts heading + body text in one block. After H5→H6 shift, these appear as `###### **heading** body text...`. This phase splits them into separate lines.

### Phase 3: Subdivision headings
Inserts H3 subdivision headings (e.g. "Session 1 Community Study", "Session 1 Weekly Disciplines") by matching `subdivision_labels` against the heading_order. Also handles rotated sidebar labels detected by `build_rotated_subdivisions`, and config-driven overrides.

### Phase 4: Cleanup
Removes misplaced headings, duplicate artifacts, and plain-text labels that now duplicate inserted H3 headings.

---

## Page Break Rejoining

`fix_page_breaks` detects and repairs text split at PDF page/column boundaries.

**Rule:** In well-edited body text, every paragraph ends with sentence-ending punctuation (`.!?:;'"*)]`). If a body text line does NOT end with such punctuation, the sentence is unfinished and the next body text line is its continuation.

**Key details:**
- Loops until stable (cascading breaks across multiple page boundaries)
- Uses separate structural prefix checks: `_STRUCT_LINE` (current line) excludes `-` and `*` so bullet/italic items can be joined; `_STRUCT_CONT` (continuation line) includes all structural prefixes
- Guards against joining numbered list items (`^\d+\.\s`)
- Minimum line length: 40 chars
- Runs ONLY after `fix_callouts` — running before callouts merges standalone callout text into body paragraphs, breaking Phase 1 removal

---

## Callout Detection

Callout/pull-quote text has a distinctive font (regular weight, ~1.6× body size). The detection works in two phases:

**`build_callout_set`** (PyMuPDF scan): Finds callout-font blocks per page, chains adjacent blocks (bridging one non-callout gap), deduplicates fragments that are substrings of longer callouts.

**`fix_callouts`** (post-processing):
- **Phase 1**: Remove standalone callout lines. Checks both plain body text AND blockquote-wrapped lines (`>` prefix stripped before matching). Uses regex matching with flexible whitespace, optional hyphens, and quote-char tolerance.
- **Phase 2**: Group consecutive body paragraphs, join with `\n\n`, search for callout regex matches across paragraph boundaries. Tag inline matches with `<Callout>` tags. Remove duplicate occurrences. Relaxed fallback regex allows one optional extra word between required words.

---

## Key Learnings

### Font data is the source of truth
The heading_map from PyMuPDF determines what IS a heading. If Marker marks text as a heading but it's not in the heading_map, the font rules didn't identify it as a heading — it gets demoted.

### Page breaks follow punctuation rules
Well-edited prose always ends paragraphs with sentence-ending punctuation. Any body text line NOT ending with punctuation is an unfinished sentence split at a page boundary. This rule has zero false positives across the entire HomeStead book (~4,600 lines).

### Callouts must run after heading hierarchy
`fix_callouts` runs after `fix_heading_hierarchy` because heading rearrangement changes line positions. If callouts ran before heading hierarchy, Phase 1 standalone removal would target the wrong lines. Similarly, `fix_page_breaks` runs after callouts to avoid merging standalone callout text into body paragraphs.

### Decorative pull-quotes in verse collections
The PDF includes decorative italic excerpts within scripture passages (e.g. `> *...but will declare to the next generation."*`). These interrupt the scripture text flow and are removed by a regex strip before blockquote continuation processing.

### Right-aligned citations
Some scripture citations are right-aligned body-size text that Marker blockquotes. `build_right_aligned_citations` detects these by checking block position (left edge past 55% page width) and `fix_blockquotes` converts them from `>` to `<<`.

### Copyright page exclusion
Pages containing © at small font are excluded from blockquote/citation detection. Copyright boilerplate shares the same small font as blockquotes but isn't quoted text.

### Conditional bold on heading demotion
When Marker assigns a heading that gets demoted, bold is preserved only if Marker's original content had `**bold**` markers.

### Multi-level heading map
The same heading text (e.g. "Introduction") can appear at different font sizes in the PDF. The heading_map stores all levels in document order and `fix_headings` consumes them sequentially.

### Rotated sidebar subdivision detection
`build_rotated_subdivisions` detects rotated (non-horizontal) text lines matching known subdivision labels and pairs them with the nearest horizontal heading on the same page.

### Artwork image generation
`fix_artwork_images` detects artwork attribution lines (pattern: `Author, Title. Year`) and generates `![Title](author_title)` image tags, deduplicating by filename.

### Fast iteration workflow
Run Marker once with `--save-raw` to get `book.raw.md`. Then iterate on post-processing only:
```bash
python run.py book.raw.md book.pdf --postprocess
```
This takes ~2 seconds instead of 6+ minutes.

### Offline pipeline testing
`testing/extract_pdf_data.py` extracts all PyMuPDF font data to a JSON file. This allows running the full post-processing pipeline without PyMuPDF installed — useful for AI-assisted debugging where the environment doesn't have fitz.

---

## Homestead Book Font Map

Body text: `TimesNewRomanPSMT @ 10pt`

| Font | Size | Ratio | Role |
|------|------|-------|------|
| TimesNewRomanPSMT | 20pt | 2.0 | H1 (session title) |
| TimesNewRomanPS-BoldMT | 20pt | 2.0 | H3 (movement title) |
| TimesNewRomanPS-ItalicMT | 14pt | 1.4 | H2 (subtitle) |
| TimesNewRomanPS-BoldMT | 14pt | 1.4 | H4 (section heading) |
| TimesNewRomanPS-BoldMT | 18pt | 1.8 | H4 (Next Steps) |
| TimesNewRomanPS-BoldMT | 12pt | 1.2 | H5 (song title, subsection) |
| TimesNewRomanPSMT | 10pt | 1.0 | Body text |
| TimesNewRomanPSMT | 8pt | 0.8 | Blockquote / citation |
| TimesNewRomanPSMT | 16pt | 1.6 | Callout (pull-quote, teal) |
| TimesNewRomanPS-BoldMT | 9.5pt | 0.95 | Running header (SKIP) |
| TimesNewRomanPS-BoldMT | 7pt | 0.7 | Verse superscript |

---

## Content-Specific Config Entries (Remaining)

These entries in `pdf_config.yaml` match on text content rather than font properties. They exist because the information is not extractable from font data alone:

| Config key | Why content-specific |
|-----------|---------------------|
| `discussion_question_labels` | Sideways decorative column headers — no extraction tool can read rotated text reliably |
| `skip_line_patterns` | Decorative labels Marker extracts that aren't real content |
| `skip_table_markers` | Decorative table headers that signal the entire table should be removed |
| `table_to_list` | Specific tables that Marker renders as tables but should be headed lists |
| `citation_patterns` | Regex pattern for "Book N:N" citation format (structural pattern, not exact text) |
| `heading_hierarchy.session_map` | Maps H1 headings to session names — structural order, not font-detectable |
| `heading_hierarchy.parts` | Part labels and their positions in the session sequence |
| `heading_hierarchy.subdivision_labels` | Labels for section subdivisions within each session |
| `heading_hierarchy.subdivision_overrides` | Subdivisions not auto-detected from heading_order |
| `front_matter_corrections` | Title/copyright page text replacements and removals |

---

## TODO

- [ ] **Auto-generate question tags** for the Noble Imprint app (structured metadata from discussion questions, reflection prompts)
- [ ] **Full book validation** — systematic comparison of all sessions against known-good output
- [ ] **Deploy to Cloud Run** — update `app.py` / `converter.py` to use the new `run.py` pipeline with template system
- [ ] **OCR evaluation** — test with `disable_ocr: False` to assess image-rendered instruction block recovery

---

## Cloud Run (marker-pdf-converter service)

The Cloud Run service is separate from the local runner and uses `app.py` + `converter.py`.

**Status:** Deploy workflow is set to `workflow_dispatch` only (manual) while iterating locally. The local `run.py` is the primary development path.

**Infrastructure:**
- GCP project: `affinity-markdown-converter`, region: `us-east1`
- Service: `marker-pdf-converter` at `https://marker-pdf-converter-z2m7tlw3yq-ue.a.run.app`
- Base image: `us-east1-docker.pkg.dev/affinity-markdown-converter/cloud-run-source-deploy/marker-pdf-base:latest`
- Model cache: `/root/.cache/datalab/models/` (not HF_HOME)
- All 5 surya models must stay loaded — setting any to `None` causes `AttributeError`
- Cold start after base image: ~35 seconds

---

## Changelog

### April 2026 — Page breaks, callout overhaul, heading hierarchy

**New passes:**
- **`fix_page_breaks`**: Rejoins text split mid-sentence at PDF page/column boundaries using punctuation-termination rule. Loops until stable, supports bullet/italic items via separate `_STRUCT_LINE`/`_STRUCT_CONT` prefix checks, guards against merging numbered list items
- **`fix_blockquote_continuations`**: Rejoins italic scripture blockquotes split at page boundaries by adding `>` prefix to lowercase continuation text
- **`fix_heading_hierarchy`**: Major 4-phase semantic heading restructuring — merges H1+H2 into session titles, inserts Part/Session/subdivision headings, shifts H3-H6 levels, splits H6+body merges, cleans up artifacts
- **`fix_heading_fragments`**: Removes orphan H1 fragments that are substrings of nearby headings
- **`fix_dedup_headings`**: Removes duplicate adjacent headings
- **`fix_artwork_images`**: Converts artwork attribution lines to image tags
- **`fix_front_matter`**: Config-driven title/copyright page cleanup
- **`fix_toc_tables`**: Removes table-of-contents tables (>80% rows have page numbers)
- **Decorative pull-quote removal**: Strips `> *...text"*` italic excerpt lines from verse collections
- **Verse superscript conversion**: Converts bold verse numbers to `<sup>` tags
- **Callout Phase 1 blockquote check**: Detects standalone callouts even when Marker wraps them in `>` blockquotes

**New font scan functions:**
- **`build_rotated_subdivisions`**: Detects rotated sidebar heading labels and pairs with page anchors
- **`build_verse_superscript_set`**: Finds small bold text that represents verse number superscripts
- **`build_right_aligned_citations`**: Detects short right-aligned body-size text for citation conversion

**Architecture changes:**
- `fix_callouts` moved to run AFTER `fix_heading_hierarchy` (heading rearrangement changes line positions)
- `fix_page_breaks` runs ONLY after callouts (prevents merging standalone callouts into body)
- Callout duplicate removal strips newlines from stitched text (`lstrip(' .\n')`)
- `heading_hierarchy` config section drives Part/Session/subdivision structure
- `front_matter_corrections` config section drives title page cleanup

### Earlier (March-April 2026) — Font-driven post-processing

- **Callout detection**: `build_callout_set` + `fix_callouts` — font-signature-based pull-quote detection with two-pass inline tagging
- **Auto-detect missing headings**: `fix_missing_headings` compares PDF heading_order against output, inserts dropped headings
- **Template system**: all book-specific config in `templates/<n>/pdf_config.yaml`; generic runner with `--template` flag
- **Ratio-based headings**: font size ratios replace absolute sizes and font names
- **`--save-raw` / `--postprocess` modes**: fast iteration without re-running Marker
- **`--dump-fonts` mode**: font calibration table for new books
- **Inline bold restoration**: `build_inline_bold_set` + `fix_inline_bold`
- **Discussion question groups**: `fix_discussion_question_groups` inserts labels at numbering restarts
- **Gemini LLM integration**: auto-detects available model (optional, used by Marker)
- **Marker bug patches**: `BlockRelabelProcessor` crash fix, Figure/Picture → Text reclassification
