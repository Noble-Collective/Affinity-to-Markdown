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
    ├── bq_set / cit_set: blockquote/citation text (8pt font)
    ├── verse_map: hymn verse text with proper line breaks
    ├── callout_texts: pull-quote text from callout font signature
    └── inline_bold: bold phrases from mixed-weight body blocks
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
[3] Post-processing pipeline (font-data-driven)
    ├── Correct heading levels using heading_map
    ├── Demote non-mapped headings (Marker guessed wrong)
    ├── Insert missing headings from heading_order
    ├── Fix blockquotes, citations, verse labels
    ├── Restore inline bold, callouts
    ├── Remove empty tables, junk content
    └── Structural cleanup
 │
 ▼  output.md
```

### Design Principles

- **Font data is the source of truth.** The heading_map built from PyMuPDF font analysis determines what IS a heading and at what level. Marker's heading assignments are corrected or overridden by this data.
- **All fixes are content-agnostic.** Post-processing rules operate on font weight, size ratios, and structural patterns — never on specific text content. If the PDF content changed (e.g. misspelling a heading), the pipeline would still work because it keys on font properties, not text strings.
- **Text is a bridge, not a target.** Text strings from the PDF connect PyMuPDF's font data to Marker's text output (matching by normalized key). The text itself is not used for formatting decisions.
- **Content-specific entries belong in template config only.** The code (`run.py`) is generic across all books. Template-specific data (font ratios, discussion labels, skip patterns) lives in `pdf_config.yaml`.
- **Fix the source when possible.** If Affinity exports a text block as an image (non-selectable text in the PDF), the best fix is to change the Affinity source — not to add OCR or config workarounds.

---

## Files

| File | Purpose |
|------|---------|
| `run.py` | Generic local runner — all conversion and post-processing logic |
| `templates/homestead/pdf_config.yaml` | Homestead book config (font ratios, headings, etc.) |
| `app.py` | Cloud Run FastAPI server (separate from local runner) |
| `Dockerfile` | Cloud Run image (uses pre-built base) |
| `Dockerfile.base` | One-time base image build (includes model downloads) |
| `cloudbuild-base.yaml` | Cloud Build config for base image |

---

## Template System

All book-specific configuration lives in `templates/<name>/pdf_config.yaml`. The runner is fully generic — no font names, absolute sizes, or text content are hardcoded in `run.py`.

### Adding a new book

```bash
# 1. Dump font analysis
python run.py newbook.pdf --dump-fonts

# Output shows:
# Body font (most frequent): TimesNewRomanPSMT @ 10.0pt
# Font                     Size  Ratio  Weight   Chars  Sample
# TimesNewRomanPS-BoldMT   20.0   2.00    bold    1234  Under God's...
# ...

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

running_header_signature:    # Block must contain ALL entries to be a running header
  - weight: bold
    min_ratio: 1.35
    max_ratio: 1.55

quote_max_ratio: 0.88    # Dominant font ratio <= this = quote/citation text
citation_max_chars: 80   # Short quote blocks → <<, long → >

verse_label_signature:   # Block must contain ALL entries to be a verse label block
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

skip_line_patterns:      # Lines matching these regexes are removed
  - '^Session \d+ (Community Study|Weekly Disciplines)'

skip_table_markers:      # Tables containing these strings are removed entirely
  - 'SEARCHING'

table_to_list:           # Convert specific tables to headed lists
  - header_contains: "Final Review"
    output_heading: "#### Final Review"
```

---

## Post-Processing Pipeline

Applied in order inside `post_process()`:

| # | Pass | What it does |
|---|------|-------------|
| 1 | `fix_pullquote_fragments` | Removes indented margin pull-quotes. Must run before blockquotes. |
| 2 | `fix_headings` | Remaps heading levels using font-derived heading_map. Demotes non-mapped headings (bold if Marker had bold, plain if not). |
| 3 | `fix_verse_labels` | Replaces `VERSE N` with `###### Verse N` + verse text from PyMuPDF. |
| 4 | `fix_double_blockquote_citations` | Converts `> > Citation` → `<< Citation`. |
| 5 | `fix_blockquotes` | Body text matching bq_set → `>`, cit_set → `<<`. |
| 6 | `fix_citations` | Standalone short paragraphs matching citation_patterns → `<<`. |
| 7 | `fix_bullet_numbers` | Fixes Marker bug: `- 1. Text` → `1. Text`. |
| 8 | `fix_hyphenation` | Merges column-break hyphenated words. |
| 9 | `fix_callouts` | Two-pass: removes standalone callout duplicates, tags inline matches with `<Callout>`. |
| 10 | `fix_empty_tables` | Removes tables where >70% of cells are empty (blank worksheet pages). |
| 11 | `fix_final_review_table` | Converts specific tables to headed numbered lists (config-driven). |
| 12 | `fix_inline_bold` | Restores inline bold in list items using font-derived bold phrase set. |
| 13 | `fix_junk_content` | Removes lines/tables matching config skip patterns. |
| 14 | `fix_missing_headings` | Compares PDF heading_order against output, inserts headings Marker dropped. Walks backward past italic instruction paragraphs. |
| 15 | `fix_missing_section_headings` | Legacy config-based fallback (no-ops with empty config). |
| 16 | `fix_discussion_question_groups` | Inserts group labels before question sets (detected by 1. restart). |
| 17 | `fix_structural_labels` | Removes ALL-CAPS labels, single-char bold, bullet chars. Demotes headings ending `:`. |
| 18 | `fix_bold_bullets` | Converts `**• Text**:` → `- **Text**:`. |

---

## Key Learnings

### Font data is the source of truth
The heading_map from PyMuPDF determines what IS a heading. If Marker marks text as a heading but it's not in the heading_map, the font rules didn't identify it as a heading — it gets demoted. This handles scripture references, "List of basic spiritual habits:", and any other text Marker incorrectly promotes to heading level. No content-based pattern matching needed.

### Auto-detection of missing headings
`build_heading_map` returns both a map (for level correction) and an ordered list (for gap detection). After all other post-processing, `fix_missing_headings` diffs the expected heading sequence against what's in the output and inserts any headings Marker dropped — before their next surviving neighbor. This replaced 10 content-specific config entries with one font-driven function.

### Conditional bold on heading demotion
When Marker assigns a heading that gets demoted, bold is preserved only if Marker's original content had `**bold**` markers. `#### **Deuteronomy 32:18**` (bold in Marker) → `**Deuteronomy 32:18**`. `#### List of basic spiritual habits:` (plain in Marker) → `List of basic spiritual habits:`.

### Callout detection from font signature
Callout/pull-quote text has a distinctive font (regular weight, 1.55-1.65× body size). `build_callout_set` scans for this signature, joins adjacent callout blocks per page, and `fix_callouts` removes standalone duplicates while tagging inline matches with `<Callout>` tags.

### Inline bold restoration
Marker loses inline bold in certain contexts (especially when content is in Figure/Picture blocks that get reclassified to Text). `build_inline_bold_set` collects bold phrases from mixed-weight body blocks via PyMuPDF, and `fix_inline_bold` restores `**bold**` in numbered/bulleted list items only (scoped to avoid false positives).

### Multi-level heading map
The same heading text (e.g. "Introduction") can appear at different font sizes in the PDF (14pt H4 vs 12pt H5). The heading_map stores all levels in document order: `{"introduction": ["####", "#####"]}`. `fix_headings` consumes them sequentially so each occurrence gets the correct level.

### Image-rendered instruction blocks
Some instruction blocks in the Affinity PDF are exported as images (non-selectable text in Adobe). PyMuPDF and Marker both can't extract text from these. The fix is to change the Affinity source to export these as real text. OCR (`disable_ocr: False`) would recover them but adds processing time and noise from decorative elements.

### Why two layers (Marker + PyMuPDF)
- **Marker** handles the hard parts: paragraph joining, column merging, list detection, blockquote detection (indentation-based)
- **PyMuPDF** handles what Marker gets wrong: heading levels (Marker uses KMeans clustering which is unreliable), verse structure, running headers, quote detection (8pt font, not indented), callout detection

### Marker drops certain headings
Large icon+heading blocks (H3 movement titles like "Seeking God's Wisdom") are dropped by Marker — it treats the icon as a separate figure and loses the heading. `fix_missing_headings` auto-detects these gaps from the PDF heading_order and inserts them at the correct position.

### Discussion question group labels
The PDF prints "SEARCHING THE TEXT / SEEKING THE TRUTH / EVALUATING OUR LIVES" as sideways decorative column headers. No extraction tool can read these reliably. They remain as content-specific entries in the template config (`discussion_question_labels`).

### Empty table detection
Blank worksheet/form pages in the PDF sometimes get extracted by Marker as mostly-empty markdown tables. `fix_empty_tables` removes tables where >70% of cells are empty — a structural check, not content-specific.

### Fast iteration workflow
Run Marker once with `--save-raw` to get `book.raw.md`. Then iterate on post-processing only:
```bash
python run.py book.raw.md book.pdf --postprocess
```
This takes ~2 seconds instead of 6+ minutes.

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
| TimesNewRomanPS-BoldMT | 7pt | 0.7 | Verse label (SKIP) |

---

## Content-Specific Config Entries (Remaining)

These entries in `pdf_config.yaml` match on text content rather than font properties. They exist because the information is not extractable from font data alone:

| Config key | Why content-specific |
|-----------|---------------------|
| `discussion_question_labels` | Sideways decorative column headers — no extraction tool can read rotated text reliably |
| `skip_line_patterns` | Decorative labels Marker extracts that aren't real content (e.g. "Session 1 Community Study") |
| `skip_table_markers` | Decorative table headers that signal the entire table should be removed |
| `table_to_list` | Specific tables that Marker renders as tables but should be headed lists |
| `citation_patterns` | Regex pattern for "Book N:N" citation format (structural pattern, not exact text) |

---

## TODO

- [ ] **Auto-generate question tags** for the Noble Imprint app to consume (structured metadata from discussion questions, reflection prompts, etc.)
- [ ] **Full book test** — run all 6+ sessions through the pipeline and validate heading structure, callouts, and verse formatting across sessions
- [ ] **Deploy to Cloud Run** — update `app.py` / `converter.py` to use the new `run.py` pipeline with template system
- [ ] **OCR evaluation** — test with `disable_ocr: False` to assess whether image-rendered instruction blocks are recovered cleanly vs. noise introduced from decorative elements

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

### April 2026 — Font-driven post-processing refactor

**New features:**
- **Callout detection**: `build_callout_set` + `fix_callouts` — font-signature-based pull-quote detection with two-pass inline tagging
- **Auto-detect missing headings**: `fix_missing_headings` compares PDF heading_order against output, inserts dropped headings. Replaces 10 content-specific `missing_section_headings` config entries
- **Multi-level heading map**: Same heading text at different font sizes gets correct level per occurrence
- **Font-driven heading demotion**: Non-mapped headings demoted to bold (if Marker had bold) or plain text. Handles scripture references, label text, etc. without content matching
- **Inline bold restoration**: `build_inline_bold_set` + `fix_inline_bold` — recovers bold in list items lost by Marker's Figure→Text reclassification
- **Empty table removal**: `fix_empty_tables` removes tables with >70% empty cells (blank worksheet pages)
- **Bold bullet fix**: `fix_bold_bullets` converts `**• Text**:` → `- **Text**:`
- **Table cell extraction fix**: Handles multi-column tables by splitting on `|` and taking first cell

**Architecture changes:**
- `build_heading_map` now returns `(heading_map, heading_order)` tuple
- `post_process` accepts `heading_order` parameter for missing heading detection
- `fix_missing_section_headings` retained as empty fallback (no config entries)
- Backward-walking insertion: missing headings inserted before italic instruction paragraphs, not after

**Design principles established:**
- All post-processing fixes must be content-agnostic (font/structure-driven)
- Content-specific entries belong only in template config, never in code
- The heading_map is the source of truth for what is a heading
- When Marker incorrectly assigns heading levels, demote based on font data, don't match on text

### Earlier (March-April 2026)
- **Template system**: all book-specific config in `templates/<n>/pdf_config.yaml`; generic runner with `--template` flag
- **Ratio-based headings**: font size ratios replace absolute sizes and font names
- **`--save-raw` / `--postprocess` modes**: fast iteration without re-running Marker
- **`--dump-fonts` mode**: font calibration table for new books
- **Verse extraction**: hymn verse structure from PyMuPDF with proper line breaks
- **Discussion question groups**: `fix_discussion_question_groups` inserts labels at numbering restarts
- **Structural label cleanup**: ALL-CAPS labels, decorative text removed
- **Double blockquote fix**: `> > Citation` → `<< Citation`
- **Gemini LLM integration**: auto-detects available model (ineffective for this use case — Marker's wrong headings have high confidence)
- **Marker bug patches**: `BlockRelabelProcessor` crash fix, Figure/Picture → Text reclassification
