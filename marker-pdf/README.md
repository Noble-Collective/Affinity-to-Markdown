# marker-pdf — PDF to Markdown Converter

Converts Noble Collective book PDFs to clean, structured Markdown using [Marker](https://github.com/datalab-to/marker) (ML-based extraction) + PyMuPDF (font-based post-processing) + a structural question-tagging system for interactive app integration.

---

## Overview

This pipeline takes a designed book PDF (created in Affinity Publisher) and produces clean Markdown with semantic heading hierarchy, correctly attributed blockquotes and citations, inline formatting, and tagged user-input areas — ready for use in a web/mobile app.

### What the pipeline does

```
┌─────────────────────────────────────────────────────────────┐
│                     BOOK PDF (input)                        │
│  Affinity Publisher → PDF with rich typography & layout      │
└──────────────────────────┬──────────────────────────────────┘
                           │
              ┌────────────┴────────────┐
              │                         │
              ▼                         ▼
   ┌──────────────────┐     ┌──────────────────────┐
   │   Marker (ML)    │     │   PyMuPDF Font Scan   │
   │                  │     │                        │
   │ • Layout detect  │     │ • Body font detection  │
   │ • Text extract   │     │ • Heading map (by font │
   │ • Para joining   │     │   size ratios)         │
   │ • List detection │     │ • Blockquote/citation  │
   │ • Blockquote     │     │   sets (small font)    │
   │   detection      │     │ • Callout texts        │
   │                  │     │ • Inline bold phrases   │
   │ Output: raw.md   │     │ • Verse superscripts   │
   │ (~80% correct)   │     │ • Right-aligned cites  │
   └────────┬─────────┘     └───────────┬────────────┘
            │                           │
            └─────────┬─────────────────┘
                      │
                      ▼
        ┌──────────────────────────┐
        │  Post-Processing Pipeline │
        │       (30+ passes)        │
        │                          │
        │  Font data corrects      │
        │  Marker's mistakes:      │
        │  • Heading levels        │
        │  • Blockquote/citation   │
        │  • Missing headings      │
        │  • Page break rejoining  │
        │  • Inline bold restore   │
        │  • Callout tagging       │
        │  • Structural hierarchy  │
        │    (Parts, Sessions,     │
        │     subdivisions)        │
        └────────────┬─────────────┘
                     │
                     ▼
        ┌──────────────────────────┐
        │   Question Tagging       │
        │                          │
        │  Structural matching:    │
        │  heading context + type  │
        │  + ordinal → wraps user  │
        │  input areas with        │
        │  <Question id="...">     │
        │  tags (377 entries)      │
        └────────────┬─────────────┘
                     │
                     ▼
        ┌──────────────────────────┐
        │    CLEAN MARKDOWN        │
        │       (output)           │
        │                          │
        │  • Semantic headings     │
        │  • Attributed quotes     │
        │  • Tagged questions      │
        │  • Inline formatting     │
        │  • ~4,600 lines          │
        └──────────────────────────┘
```

### Key design principles

1. **Font data is the source of truth.** PyMuPDF's font analysis determines what IS a heading, blockquote, or citation — not Marker's guesses. Marker provides the text; PyMuPDF provides the formatting truth.

2. **All fixes are rule-based, not text-based.** Post-processing rules operate on font weight, size ratios, and structural patterns. If you changed every word in the book, the pipeline would still work because it keys on font properties.

3. **Template config, not hardcoded strings.** The code (`run.py`) is generic. All book-specific data (font ratios, heading labels, skip patterns) lives in `templates/<book>/pdf_config.yaml`.

4. **Question tagging is structural.** Questions are matched by heading context + type + ordinal position — never by text content. The `text` field in `questions_final.yaml` is for human review only; the code never reads it.

5. **Diagnose before fixing.** When output looks wrong: check raw Marker output → check PyMuPDF font data → trace through pipeline passes → identify root cause → design a rule-level fix.

### Three-file system

| File | Role | Content-specific? |
|------|------|-------------------|
| `run.py` | All pipeline logic | **No** — generic across books |
| `templates/homestead/pdf_config.yaml` | Font ratios, heading rules, hierarchy | **Yes** — per-book config |
| `templates/homestead/questions_final.yaml` | Question IDs, types, ordinals | **Yes** — per-book question map |

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

### Pipeline layers

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
    ├── inline_bold: [(phrase, context_line), ...] with PDF line context
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
    ├── Restore context-aware inline bold, callouts
    ├── Convert artwork references to image tags
    ├── Remove empty tables, decorative content
    └── Structural cleanup + final normalization
 │
 ▼
[4] Question tagging (structural matching)
    ├── Walk document tracking heading context
    ├── Classify each line by type (numbered, italic_prompt, fill_in, etc.)
    ├── Match by heading_context + type + ordinal against questions config
    └── Wrap matched lines with <Question id="...">...</Question>
 │
 ▼  output.md
```

### How question tagging works

The question tagger doesn't search for text — it navigates the document structure:

```
Document heading stack          Question config entry
─────────────────────           ─────────────────────
# PART ONE: Preparation         id: Home-ParOnePre-SesOne-...-SeaTex-3
## Session One                   ↑
### Session 1 Community Study    Built from heading abbreviations:
#### Exploring the Biblical Text  Par→Par, One→One, Pre→Pre, etc.
##### Discussion Questions
###### Searching the Text        type: numbered
                                 ordinal: 3  ← 3rd numbered item
   1. first question                         under this heading stack
   2. second question
→  3. THIS GETS TAGGED  ←──────── match!
```

The abbreviation function (`_q_abbrev`) takes the first 3 characters of each significant word in a heading, skipping stop words. This produces deterministic IDs that the post-processor re-derives from the heading stack as it walks the document. No text matching needed.

**Question types:**

| Type | Count | Pattern | Example |
|------|-------|---------|---------|
| `numbered` | 255 | `^\d+\.\s` | `1. What most excites you about parenting?` |
| `italic_prompt` | 43 | `*...*` | `*Record your observations below.*` |
| `fill_in_bullet` | 37 | `- ...…` | `- These are ways that I am **fragile**…` |
| `bold_bullet` | 18 | `- **Label**:` | `- **Reflecting on Your Past**: How would you...` |
| `heading_prompt` | 8 | `###### ...` | `###### Record Your Thoughts Below` |
| `standalone_prompt` | 7 | specific phrases | `How can I pray for **other members**...` |
| `prayer_fill` | 6 | `God,...…` | `God, these are the ways I fell short today…` |
| `fill_in_line` | 3 | `**bold**...…` | `This is what I **appreciated** about my upbringing…` |

---

## Files

| File | Purpose |
|------|---------|
| `run.py` | Generic local runner — all conversion, post-processing, and question tagging logic |
| `templates/homestead/pdf_config.yaml` | Homestead book config (font ratios, headings, hierarchy, etc.) |
| `templates/homestead/questions_final.yaml` | Question tagging config — 377 entries with structural IDs |
| `testing/claude debug scripts/extract_pdf_data.py` | Extracts PyMuPDF font data to JSON for offline pipeline testing |
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

heading_hierarchy:       # Semantic heading restructuring
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

Applied in order inside `post_process()`. Each pass uses font data from PyMuPDF to correct Marker's output.

### Early cleanup

| Pass | What it does |
|------|-------------|
| Image/rule strip | Remove Marker image tags and horizontal rules |
| `fix_pullquote_fragments` | Remove indented margin pull-quotes |
| `fix_split_bold_headings` | Join consecutive bold lines split by Marker (e.g. `**At All Times:**` + `**Building Worship...**` → single bold line) |
| `fix_headings` | Remap heading levels using font-derived heading_map |

### Verse & blockquote correction

| Pass | What it does |
|------|-------------|
| `fix_verse_labels` | Replace `VERSE N` with `###### Verse N` + verse text from PyMuPDF |
| `fix_double_blockquote_citations` | Convert `> > Citation` → `<< Citation` |
| `fix_blockquotes` | Validate and correct Marker's blockquotes against PyMuPDF data. Add `>` to untagged blockquote text, convert right-aligned text to `<<` citations, strip `>` from numbered items Marker incorrectly blockquoted |
| Decorative pull-quote removal | Strip `> *...text"*` italic excerpt lines |
| `fix_blockquote_continuations` | Rejoin italic scripture blockquotes split at page boundaries |
| `fix_citations` | Standalone lines matching citation regex patterns → `<<` |

### Text repair

| Pass | What it does |
|------|-------------|
| `fix_bullet_numbers` | Fix Marker bug: `- 1. Text` → `1. Text` |
| `fix_hyphenation` | Merge column-break hyphenated words |

### Table & content cleanup

| Pass | What it does |
|------|-------------|
| `fix_empty_tables` | Remove tables where >70% of cells are empty |
| `fix_toc_tables` | Remove tables where >80% of rows have page numbers |
| `fix_final_review_table` | Convert specific tables to headed numbered lists. Handles two Marker patterns: header inside table (Pattern A) and heading before table (Pattern B) |
| `fix_inline_bold` | Restore inline bold using context-aware phrase matching |
| `fix_junk_content` | Remove lines/tables matching config skip patterns |
| `fix_artwork_images` | Convert artwork attributions to `![Title](filename)` image tags |

### Heading structure

| Pass | What it does |
|------|-------------|
| `fix_missing_headings` | Compare PDF heading_order against output, insert dropped headings |
| `fix_dedup_headings` | Remove duplicate adjacent headings |
| `fix_heading_fragments` | Remove orphan H1 fragments |
| `fix_missing_section_headings` | Config-based fallback for headings not auto-detected |
| `fix_discussion_question_groups` | Insert group labels before question sets (detected by 1. restart) |

### Structural cleanup

| Pass | What it does |
|------|-------------|
| `fix_structural_labels` | Remove ALL-CAPS labels, single-char bold, bare bullet chars. Convert `> •` and `<< •` blockquote-wrapped bullets to `- `. Demote headings ending `:` |
| `fix_bold_bullets` | Convert `**bullet Text**:` → `- **Text**:` |
| Citation bold strip | Remove bold from `<< **text**` citation lines |
| `fix_front_matter` | Config-driven line removal and text replacement for title/copyright pages |

### Heading hierarchy (semantic restructuring)

| Phase | What it does |
|------|-------------|
| Phase 1 | Walk H1 headings, match to `session_map`, insert `# PART` and `## Session` headings, merge H1+H2 into `#### Title: Subtitle` |
| Phase 2 | Level shifts: H6→bold, H3-H5→shift down, H2→`####`. Repositions PART intro paragraphs. Splits H6+body merges |
| Phase 3 | Insert H3 subdivision headings from `subdivision_labels`, rotated sidebar labels, and config overrides |
| Phase 4 | Remove misplaced headings, duplicates, and plain-text labels that duplicate inserted H3s |

### Callouts & page breaks

| Pass | What it does |
|------|-------------|
| `fix_callouts` | Phase 1: remove standalone callout lines. Phase 2: tag inline matches with `<Callout>` across paragraph groups |
| Callout adjacency merge | Merge `</Callout> <Callout>` into single span |
| `fix_page_breaks` | Rejoin text split mid-sentence at page boundaries using punctuation-termination rule. Ellipsis (`…`) recognized as sentence-ending for fill-in prompts |
| Callout punctuation | Move trailing punctuation inside `</Callout>` tags (must run AFTER `fix_page_breaks`) |

### Final normalization & question tagging

| Pass | What it does |
|------|-------------|
| Verse superscript conversion | Bold verse numbers → `<sup>103:1</sup>` |
| Bold verse spacing | Remove extra blank after `**Verse N**` lines |
| Table bullet fix | `<br>•<br>` → `<br>• ` |
| Triple-blank collapse | `\n{3,}` → `\n\n` |
| `fix_questions` | Structural question tagging — walks heading stack, classifies lines by type, matches against `questions_final.yaml` by context+type+ordinal, wraps with `<Question>` tags |

---

## Question Tagging System

### Overview

The question tagger wraps user-input areas (discussion questions, reflection prompts, fill-in blanks, prayer prompts) with `<Question id="...">...</Question>` tags for the Noble Imprint app.

### How it works

```
questions_final.yaml                    Document
────────────────────                    ────────
id: Home-ParOnePre-SesOne-              ## Session One
    ...-SeaTex-3                        ### Session 1 Community Study
type: numbered                          ...
ordinal: 3                              ###### Searching the Text
                                        1. first question
  Heading context match ─────────┐      2. second question
  + type match (numbered) ───────┤  →   3. TAGGED ← ordinal 3
  + ordinal match (3rd) ─────────┘
```

**Matching is purely structural:**
- The ID encodes the heading hierarchy as abbreviations
- The post-processor re-derives the same abbreviation from the heading stack
- Lines are classified by structural pattern (starts with `\d+.`, starts with `- **`, starts with `*...*`, etc.)
- The ordinal counts items of each type under each heading context

### Config file format (`questions_final.yaml`)

```yaml
book: HomeStead
prefix: Home

questions:
  - id: Home-ParOnePre-SesOne-Ses1ComStu-SeeGodWis-BibWis-GroDis-1
    type: numbered
    ordinal: 1
    text: "1. How would you describe your Christian faith..."    # human review only
    path: "PART ONE > Session One > ... > Group Discussion"      # human review only
```

The code reads only `id` (to extract heading context base + ordinal) and `type`. The `text` and `path` fields exist solely for human review when maintaining the config.

### Adding questions for a new book

1. Run the pipeline to produce clean markdown output
2. Walk the output section by section, identifying user-input areas
3. Build `questions_final.yaml` entries using the heading abbreviation scheme
4. Validate: run the pipeline and verify all entries tag correctly

### Coverage (HomeStead)

- **Part 1 (Preparation):** Introduction (21) + Sessions 1-6 (~35-47 each) = 258 entries
- **Part 2 (Challenge):** Daily Devotionals (40) + Outdoor Experiences (28) + Mentoring Sessions (44) = 112 entries
- **Part 3 (Celebration):** Personal Testimony + Community Confession + Celebration = 7 entries
- **Total: 377 entries**

---

## Heading Hierarchy System

`fix_heading_hierarchy` restructures the flat font-based heading levels into a semantic document hierarchy with Parts, Sessions, and subdivisions. This is the most complex post-processing pass.

### Phase 1: Session structure
Walks the H1 headings and matches them to `session_map` entries. For each session, inserts `# PART` headings, `## Session Name` headings, and merges H1+H2 into `#### Title: Subtitle`.

### Phase 2: Level shifts
H6 → bold text, H3-H5 → shift down one level, H2 → `####`. Also repositions PART intro paragraphs and splits H6+body merges.

### Phase 3: Subdivision headings
Inserts H3 subdivision headings by matching `subdivision_labels` against the heading_order. Handles rotated sidebar labels and config overrides.

### Phase 4: Cleanup
Removes misplaced headings, duplicate artifacts, and plain-text labels that duplicate inserted H3s.

---

## Page Break Rejoining

`fix_page_breaks` detects and repairs text split at PDF page/column boundaries.

**Rule:** In well-edited body text, every paragraph ends with sentence-ending punctuation. If a body text line does NOT end with such punctuation, the sentence is unfinished and the next body text line is its continuation.

**Key details:**
- Ellipsis (`…` / `...`) counts as sentence-ending punctuation — fill-in prompts end with ellipsis and should NOT be joined to the next line
- Quote characters (`"`, `'`) only count as sentence-ending if preceded by `.!?'`
- Loops until stable (cascading breaks across multiple page boundaries)
- Guards against joining numbered list items
- Runs ONLY after `fix_callouts` — running before would merge standalone callout text into body paragraphs

---

## Callout Detection

Callout/pull-quote text has a distinctive font (regular weight, ~1.6x body size).

**`build_callout_set`** (PyMuPDF scan): Finds callout-font blocks per page, chains adjacent blocks, deduplicates fragments.

**`fix_callouts`** (post-processing):
- **Phase 1**: Remove standalone callout lines (including blockquote-wrapped)
- **Phase 2**: Tag inline matches with `<Callout>` across paragraph groups

**Critical ordering:** Callout punctuation (`</Callout>.` → `.</Callout>`) MUST run after `fix_page_breaks`. Lines ending `.</Callout>` end with `>` which isn't sentence-ending punctuation — running it before page breaks caused 40+ paragraph merge regression.

---

## Context-Aware Inline Bold

Marker loses inline bold in certain contexts. The pipeline restores it using font data with context awareness.

**Problem:** Short words like "Church" appear bold in discussion labels AND plain in other contexts. Without context, `fix_inline_bold` would bold every occurrence.

**Solution:** `build_inline_bold_set` returns `[(phrase, context_line), ...]`. Before applying bold, `fix_inline_bold` checks that enough context words from the PDF line appear in the markdown line. This means `"Church"` only gets bolded in lines containing its context words (e.g. "priority", "family") — not in unrelated bullet lists.

---

## Key Learnings

- **Font data is the source of truth.** The heading_map from PyMuPDF determines what IS a heading. Marker's assignments are corrected by this data.
- **Page breaks follow punctuation rules.** Well-edited prose ends every paragraph with sentence-ending punctuation. Any line NOT ending with punctuation is split mid-sentence. Zero false positives across ~4,600 lines.
- **Ellipsis is sentence-ending punctuation.** Fill-in prompts end with `…` — without recognizing this, `fix_page_breaks` joins them to the next line.
- **Pass ordering is critical.** Callout punctuation must come after page breaks. Callouts must come after heading hierarchy. Question tagging must come last (after all structural changes).
- **Quote chars need special handling.** `"I will dwell in the house of the Lord forever"` ends with `"` but the sentence continues. Smart quote-ending requires `.!?'` before the quote character.
- **Context-aware bold prevents false positives.** Short common words need PDF line context to avoid bolding in wrong locations.
- **Marker blockquotes need validation.** Marker sometimes blockquotes non-blockquote content (e.g. numbered questions). The pipeline strips `>` from numbered items, which are never legitimate blockquotes.
- **The converter surfaces PDF source issues.** When text appears truncated in output, check the PDF itself — the converter faithfully reproduces what's in the PDF.
- **bq_set only covers small-font blockquotes.** `build_blockquote_set` catches text in fonts smaller than body size. Blockquotes that Marker identifies by indentation (same font size) are NOT in bq_set — don't validate all Marker blockquotes against it.

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

## Cloud Run (marker-pdf-converter service)

The Cloud Run service is separate from the local runner and uses `app.py` + `converter.py`.

**Status:** Deploy workflow is set to `workflow_dispatch` only (manual) while iterating locally. The local `run.py` is the primary development path.

**Infrastructure:**
- GCP project: `affinity-markdown-converter`, region: `us-east1`
- Service: `marker-pdf-converter` at `https://marker-pdf-converter-z2m7tlw3yq-ue.a.run.app`
- Base image: `us-east1-docker.pkg.dev/affinity-markdown-converter/cloud-run-source-deploy/marker-pdf-base:latest`

---

## Changelog

### April 2026 — Question tagging, pipeline fixes

**Question tagging system:**
- `fix_questions()` — structural matching by heading context + type + ordinal
- `questions_final.yaml` — 377 entries covering all user-input areas in HomeStead
- `_q_abbrev()` — deterministic heading abbreviation (first 3 chars of significant words)
- `_q_classify()` — structural line classification (8 types: numbered, italic_prompt, fill_in_bullet, bold_bullet, heading_prompt, standalone_prompt, prayer_fill, fill_in_line)

**Pipeline fixes:**
- `fix_page_breaks`: ellipsis (`…`) added to `_END_PUNCT` — prevents fill-in prompts from being joined to next line
- `fix_final_review_table`: Pattern B handles heading-before-table layout (Sessions 4/5)
- `fix_citations`: removed short-after-blockquote heuristic — caused false positives on prayer fills and section labels. All legitimate citations are caught by regex patterns and PyMuPDF right-aligned detection
- `fix_structural_labels`: `> •` and `<< •` blockquote-wrapped bullets → `- ` (Marker artifact)
- `fix_split_bold_headings`: joins consecutive bold lines split by Marker (e.g. `**At All Times:**` + `**Building Worship...**`) before heading detection
- `fix_blockquotes`: strips `>` from numbered items — Marker sometimes blockquotes indented questions
- `_q_classify`: prayer_fill requires ellipsis ending — prevents scripture quotes starting with "God," from consuming question slots

### April 2026 (earlier) — Context-aware bold, smart quote-ending, callout punctuation

**Context-aware inline bold:**
- `build_inline_bold_set` returns `[(phrase, context_line), ...]`
- `fix_inline_bold` checks context word overlap before applying bold
- Eliminates false positives on short common words

**Smart quote-ending in fix_page_breaks:**
- Quote chars only count as sentence-ending if preceded by `.!?'`
- `_ends_sentence()` helper with separate `_END_PUNCT` and `_QUOTE_CHARS` sets

**Callout punctuation ordering:**
- `</Callout>.` → `.</Callout>` — must run after `fix_page_breaks`

### March-April 2026 — Font-driven pipeline, heading hierarchy, template system

- Callout detection, auto-detect missing headings, template system
- Ratio-based headings, `--save-raw`/`--postprocess` modes, `--dump-fonts`
- Inline bold restoration, discussion question groups
- Page break rejoining, blockquote continuations, heading hierarchy
- Artwork image generation, front matter corrections
- Gemini LLM integration, Marker bug patches
