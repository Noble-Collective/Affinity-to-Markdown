# marker-pdf — PDF to Markdown Converter

Converts Noble Collective book PDFs to clean Markdown using [Marker](https://github.com/datalab-to/marker) (ML-based extraction) + PyMuPDF (font-based post-processing).

---

## Quick Start

```bash
cd marker-pdf
source venv311/Scripts/activate   # Windows Git Bash (Python 3.11 venv)

# One-time: save Marker's raw output (6-min ML step)
python run.py "path/to/book.pdf" --save-raw

# Fast iteration: re-run post-processing only (seconds, not minutes)
python run.py raw.md book.pdf --postprocess

# Full conversion
python run.py "path/to/book.pdf"

# Font calibration for a new book
python run.py "path/to/book.pdf" --dump-fonts

# LLM heading correction (optional, requires Gemini API key)
export GOOGLE_API_KEY="your-key"
python run.py "path/to/book.pdf"
```

**Requirements:** Python 3.11, `pip install pyyaml pymupdf marker-pdf` in venv311.

---

## Architecture

Two-layer pipeline:

```
PDF
 │
 ▼
[1] Marker (ML)
    ├── Layout detection (surya model, ~6 min on CPU)
    ├── Text extraction (pdftext)
    ├── Paragraph joining, list detection, blockquote detection
    └── Optional: LLMSectionHeaderProcessor (Gemini API)
         └── Only corrects headings Marker is *uncertain* about —
             doesn't help with confidently-wrong headings
 │
 ▼  raw.md  (Marker's output, saved with --save-raw)
 │
 ▼
[2] PyMuPDF post-processing (run.py)
    ├── Body font auto-detection (most frequent font = body)
    ├── Heading map: ratio-based (font_size / body_size) → H1-H5
    ├── Skip set: running headers, page numbers, decorative text
    ├── Blockquote/citation sets: 8pt text → > or <<
    ├── Verse map: extract hymn verse lines with proper formatting
    └── Post-processing passes (see below)
 │
 ▼  output.md
```

---

## Files

| File | Purpose |
|------|---------|
| `run.py` | Generic local runner — all conversion logic |
| `templates/homestead/pdf_config.yaml` | Homestead book config (font ratios, headings, etc.) |
| `app.py` | Cloud Run FastAPI server (separate from local runner) |
| `Dockerfile` | Cloud Run image (uses pre-built base) |
| `Dockerfile.base` | One-time base image build (includes model downloads) |
| `cloudbuild-base.yaml` | Cloud Build config for base image |

---

## Template System

All book-specific configuration lives in `templates/<name>/pdf_config.yaml`. The runner is fully generic — no font names or absolute sizes are hardcoded anywhere in `run.py`.

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
python run.py newbook.pdf --template newbook
```

### pdf_config.yaml keys

```yaml
body_font: auto          # "auto" = most frequent font; or exact font name string

headings:                # Rules matched top-to-bottom; first match wins
  - weight: regular      # regular | bold | italic | bold-italic
    min_ratio: 1.85      # font_size / body_font_size
    max_ratio: 2.15
    level: 1             # Markdown heading level (1-6)

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

citation_patterns:       # Python regex; standalone short lines matching these → <<
  - '^[A-Z][a-zA-Z]+\s+\d+:\d+...$'

missing_section_headings:    # H3 headings Marker drops (large icon+heading blocks)
  - italic_snippet: "focus your thinking around the key idea"
    heading: "### Seeking God's Wisdom"

discussion_question_labels:  # Inserted before each group of N questions (by 1. restart)
  - "##### Searching the Text"
  - "##### Seeking the Truth"
  - "##### Evaluating Our Lives"
```

---

## Post-Processing Passes

Applied in this order inside `post_process()`:

| Pass | What it does |
|------|-------------|
| `fix_pullquote_fragments` | Removes PDF margin pull-quotes (Marker emits with leading space). **Must run before blockquotes** or they'd be converted to `>` lines. |
| `fix_headings` | Remaps Marker headings using heading_map (ratio-based). Promotes plain body text that matches a heading key. Strips `**bold**` / `*italic*` wrappers Marker adds. |
| `fix_verse_labels` | Replaces `#### VERSE N` with `###### Verse N` + verse text from PyMuPDF. Skips all of Marker's merged verse text. Adds blank line after each verse block. |
| `fix_double_blockquote_citations` | Converts `> > Citation` → `<< Citation` (Marker double-blockquote syntax). |
| `fix_blockquotes` | Converts body text lines that match bq_set → `>`, cit_set → `<<`. |
| `fix_citations` | Converts standalone short paragraphs matching citation_patterns → `<<`. Also converts short text after `>` or `<<` lines. |
| `fix_bullet_numbers` | Fixes Marker bug: `- 1. Text` → `1. Text`. |
| `fix_hyphenation` | Merges column-break hyphenated words split across lines. |
| `fix_missing_section_headings` | Inserts H3 headings Marker drops, detected by the italic instruction paragraph that follows each one. Configured in `missing_section_headings`. |
| `fix_discussion_question_groups` | Inserts group headings before each question set (detected by 1. numbering restart). Configured in `discussion_question_labels`. |
| `fix_structural_labels` | Removes all-caps schedule labels (PRAYERS, CATECHISM, etc.). Removes single-char bold artifacts (`**S**`). Demotes headings ending with `:` to body text. Converts `•` bullets to `- `. |

---

## Key Learnings

### Why font ratios instead of absolute sizes
Every book template may use different fonts or slightly different sizes. Expressing headings as `bold @ 1.4× body size` rather than `TimesNewRomanPS-BoldMT @ 14pt` makes the config portable across book templates.

### Why two layers (Marker + PyMuPDF)
- **Marker** handles the hard parts: paragraph joining, hyphenation de-wrapping across columns, list detection, blockquote detection (indentation-based)
- **PyMuPDF** handles what Marker gets wrong: heading levels (Marker uses KMeans clustering on font sizes which is unreliable), verse structure, running headers, blockquotes in this book (8pt font, not indented)

### Marker drops certain headings
The large icon+heading blocks (H3 movement titles like "Seeking God's Wisdom") are dropped by Marker's layout detection — it treats the icon as a separate figure and loses the heading. Fix: detect the distinctive italic instruction paragraph that follows each heading and insert the H3 before it (`missing_section_headings` config).

### LLM heading correction is ineffective for this use case
`LLMSectionHeaderProcessor` (Gemini) only runs on headings Marker is *uncertain* about (low confidence score). For this book, Marker's wrong headings have high confidence — the KMeans model confidently assigns wrong levels. The LLM processor finds no ambiguous blocks to correct. Our font ratio approach works better.

### Discussion question group labels
The PDF prints "SEARCHING THE TEXT / SEEKING THE TRUTH / EVALUATING OUR LIVES" as sideways decorative column headers. Marker extracts only one of them inconsistently. Fix: detect the 1–4 numbering restart within the Discussion Questions section and insert the appropriate heading at each group boundary.

### Verse text deduplication
The verse_map extracts properly line-broken verse text from PyMuPDF. After inserting it, `fix_verse_labels` skips everything up to the next `#` heading — this skips ALL of Marker's merged verse text (which spans multiple lines/paragraphs with blank lines between).

### Marker bug: BlockRelabelProcessor crash
`BlockRelabelProcessor` crashes when `block.top_k.get(block.block_type)` returns `None`. Patched via monkey-patch in `patch_block_relabel()`. Fixed with a simple `if confidence is None: continue`.

### Gemini API model availability
- `gemini-2.0-flash` is not available to new API keys (404 NOT_FOUND)
- `get_available_gemini_model()` queries `client.models.list()` and picks the best available model automatically
- Billing must be enabled on the Google Cloud project for any Gemini API calls

### Fast iteration workflow
Run Marker once with `--save-raw` to get `book.raw.md`. Then iterate on post-processing only:
```bash
python run.py book.raw.md book.pdf --postprocess
```
This takes ~2 seconds instead of 6 minutes. Upload `book.raw.md` to a conversation with Claude to iterate on post-processing entirely without running anything locally.

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
| TimesNewRomanPS-BoldMT | 12pt | 1.2 | H5 (song title) |
| TimesNewRomanPSMT | 10pt | 1.0 | Body text |
| TimesNewRomanPSMT | 8pt | 0.8 | Blockquote / citation |
| TimesNewRomanPS-BoldMT | 9.5pt | 0.95 | Running header small-caps (SKIP) |
| TimesNewRomanPS-BoldMT | 7pt | 0.7 | Verse label small-caps (SKIP) |

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

**To rebuild base image (one-time, ~1hr):**
```bash
gcloud builds submit . --config cloudbuild-base.yaml \
  --project affinity-markdown-converter --timeout 3600
```

---

## Changelog

### Current (April 2026)
- **Template system**: all book-specific config in `templates/<name>/pdf_config.yaml`; generic runner with `--template` flag
- **Ratio-based headings**: font size ratios replace absolute sizes and font names
- **`--save-raw` / `--postprocess` modes**: fast iteration without re-running Marker
- **`--dump-fonts` mode**: font calibration table for new books
- **Verse extraction**: hymn verse structure from PyMuPDF with proper line breaks
- **Missing H3 headings**: `fix_missing_section_headings` inserts headings Marker drops
- **Discussion question groups**: `fix_discussion_question_groups` inserts Searching/Seeking/Evaluating labels
- **Verse spacing**: blank line after each verse block before next heading
- **Structural label cleanup**: PRAYERS, CATECHISM, MUTUAL ENCOURAGEMENT, etc. removed
- **Double blockquote fix**: `> > Citation` → `<< Citation`
- **Pull-quote fragment removal**: leading-space margin callouts removed
- **Heading colon fix**: headings ending with `:` demoted to body text
- **Gemini LLM integration**: auto-detects available model; `llm_service` passed as separate `PdfConverter` kwarg (not in config dict)

### Earlier iterations
- **It1-4**: Baseline Marker config tuning (level_count, blockquote thresholds)
- **It5**: PyMuPDF heading map added (major quality jump)
- **It6**: `force_layout_block=Text` tested and abandoned (produces blobs)
- **It7**: 8pt blockquote detection, curly quote fix, body→heading promotion
- **It8**: PageHeaderProcessor removed, bold stripped from headings, verse labels
- **It9**: LLM wired correctly but ineffective (all headings have high confidence)
