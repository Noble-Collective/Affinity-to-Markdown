# Architecture & Technical Reference

This document captures the design decisions, technical learnings, and implementation patterns for the Affinity-to-Markdown conversion system. It exists so future development (by humans or Claude) can build on prior work without re-discovering the same things.

---

## System Overview

Two independent Cloud Run services, each with its own deploy workflow:

| Service | Cloud Run Name | Source | Memory | Purpose |
|---------|---------------|--------|--------|---------|
| AFPUB Converter | `afpub-converter` | repo root | 2 GB | Converts `.afpub` binary files → Markdown using a custom binary parser |
| Marker PDF Converter | `marker-pdf-converter` | `marker-pdf/` | 8 GB | Converts `.pdf` files → Markdown using the Marker ML library |

The web UI (`static/index.html`) has a format toggle (PDF / AFPUB) that routes to the appropriate service.

Large files (>30 MB) bypass Cloud Run's HTTP body limit via GCS signed upload URLs. Small files go direct.

---

## Why We Abandoned AFPUB Binary Parsing

The original approach (`afpub_to_markdown.py`) reverse-engineered Affinity Publisher's proprietary compressed binary format. It worked well for Session 1 of the Homestead book but had fundamental fragility:

- **No explicit style name table in the binary.** Affinity stores style names only in its runtime object graph. The binary contains numeric style IDs (e.g. `311`, `192`) but no reliable name→ID mapping table we could parse.
- **IDs are not portable across templates.** The same named style ("Header Level 1") has different numeric IDs in files from different book templates. Every new book requires a calibration run (`--analyze-styles`) and manual mapping.
- **Any Affinity update could silently break the parser.** The binary format is undocumented and proprietary.

The afpub converter remains in the repo and deployed as a fallback, but new development focuses on PDF export.

---

## PDF Extraction Approach: Why Marker

### What We Tried

1. **Custom PyMuPDF extractor** (`pdf_to_markdown.py`): Reads per-span font metadata (font name + size) and maps to Markdown roles via `pdf_styles.yaml`. Works, but requires per-template calibration and hand-coding of every structural pattern (running headers, verse labels, citation detection, paragraph joining). 12,000-line output vs 754-line reference on first attempt — fundamental issues with paragraph reflow.

2. **Docling** (IBM Research): OOMed at 4 GB even on 11-page extracts. Its full pipeline loads a layout ML model regardless of OCR settings. Its native text backend (`DoclingParseDocumentBackend`) is essentially a better PyMuPDF without structure understanding.

3. **Marker** (datalab-to): Selected. See rationale below.

### Why Marker

Marker solves the exact problems we were hand-coding:

| Problem | Our PyMuPDF approach | Marker built-in |
|---------|---------------------|-----------------|
| Heading level assignment | Manual `pdf_styles.yaml` per template | `SectionHeaderProcessor`: KMeans clustering on font heights, auto-discovers hierarchy |
| Running header removal | Heuristic all-caps detection | `IgnoreTextProcessor`: fuzzy-matches text appearing on 20%+ of pages, flags `ignore_for_output` |
| Page header handling | Y-coordinate threshold | `PageHeaderProcessor`: dedicated block type |
| Blockquote detection | Short-block heuristics | `BlockquoteProcessor`: spatial indentation analysis |
| List merging | Per-block prefix detection | `ListProcessor`: merges lists across pages and columns |
| Text paragraph reflow | Sentence-boundary heuristics | `TextProcessor`: handles column breaks and page breaks |
| Line number stripping | Not implemented | `LineNumbersProcessor`: dedicated processor |

The tradeoff: Marker requires ~6-8 GB RAM (5 Surya ML models) and a large Docker image with models baked in. Manageable on Cloud Run with 8 GB allocation.

---

## Homestead Book PDF — Font Analysis

> Discovered via `--dump-fonts` on `HomeStead-Interior-Affinity Design-v1.001.pdf`
> Body font: `TimesNewRomanPSMT @ 10.0pt` (301,556 chars — most common by far)

### Font → Semantic Role Mapping

| Font | Size | Role | Notes |
|------|------|------|-------|
| `TimesNewRomanPSMT` | 20.0 | H1 (Session title) | Regular weight — "Under God's Fatherly Care" |
| `TimesNewRomanPS-BoldMT` | 20.0 | H3 (Movement title) | Bold weight — "Tuning Our Hearts to the Lord" |
| `TimesNewRomanPS-ItalicMT` | 14.0 | H2 (Session subtitle) | "Building a Home Devoted to God" |
| `TimesNewRomanPS-BoldMT` | 14.0 | H4 (Section heading) | "Community Confession", "Key Idea", etc. |
| `TimesNewRomanPS-BoldMT` | 18.0 | H4 (special heading) | "Next Steps" |
| `TimesNewRomanPS-BoldMT` | 12.0 | H5 (song/sub-section) | "The Tender Love a Father Has" |
| `TimesNewRomanPSMT` | 10.0 | Body text | BODY — most common |
| `TimesNewRomanPS-BoldMT` | 10.0 | Inline bold | "All:", "Reader:", "As priests..." |
| `TimesNewRomanPS-ItalicMT` | 10.0 | Inline italic | "most holy work", "most humble walk" |
| `TimesNewRomanPS-ItalicMT` | 9.5 | p_italic (instructions) | "Unite your hearts together..." |
| `TimesNewRomanPSMT` | 8.0 | Blockquote / citation | Scripture quotes AND citations — distinguished by length |
| `TimesNewRomanPS-ItalicMT` | 8.0 | Italic within citation | Book titles in attribution lines |
| `TimesNewRomanPS-BoldMT` | 6.0 | Superscript verse numbers | "103:1", "2", "3" ... in Psalm 103 |
| `TimesNewRomanPS-BoldMT` | 9.5 | SKIP | Running header small-caps "NTRODUCTION", "ESSION" |
| `TimesNewRomanPS-BoldMT` | 7.0 | SKIP | Verse label small-caps "ERSE" |

### Critical Discoveries

**Session title vs Movement title are the same apparent size but different weights:**
- Regular 20pt = Session title (H1)
- Bold 20pt = Movement title (H3)
- These are distinguishable by font name, not just size

**Running headers use a drop-cap + small-caps pattern:**
- "INTRODUCTION SESSION ONE" = Bold 14pt drop caps ("I", "S", "O") + Bold 9.5pt small-caps ("NTRODUCTION", "ESSION", "NE") interleaved in one block
- Marker's `IgnoreTextProcessor` should catch these via repetition detection

**Verse labels are drop-cap + small-caps too:**
- "VERSE 4" = Bold 10pt "V" + Bold 7pt "ERSE" + Bold 10pt "4"
- The 7pt span is the distinctive marker

**Blockquotes and citations are the same font/size (8pt Regular):**
- Long blocks (≥100 chars) = blockquote `>`
- Short blocks (<100 chars) = citation `<<`

**The whole-book PDF is 481 pages.** Front matter ends around page 62. Session 1 starts at page 63.

---

## Marker: Complete Configurable Parameter Reference

All parameters discovered by reading Marker/Surya source. Passed as a flat dict to `PdfConverter`.

### SectionHeaderProcessor
| Parameter | Default | Notes |
|-----------|---------|-------|
| `level_count` | 4 | Number of KMeans heading clusters to find. 6 = too many H1s for this PDF. 3 works better. |
| `merge_threshold` | 0.25 | When adjacent clusters are within this ratio, merge them. Increase → fewer distinct heading levels. |
| `default_level` | 2 | Heading level for blocks that don't fit any cluster. Set to 3 for this book. |
| `height_tolerance` | 0.99 | Block height must be ≥ min_height × tolerance to match a cluster. |

### BlockquoteProcessor
| Parameter | Default | Notes |
|-----------|---------|-------|
| `min_x_indent` | 0.1 | Fraction of block width a block must be indented to be a blockquote. 0.01–0.03 works better for this PDF. |
| `x_start_tolerance` | 0.01 | How precisely consecutive blockquote blocks must be left-aligned. Increase to 0.05 for looser matching. |
| `x_end_tolerance` | 0.01 | Same for right alignment. |

### IgnoreTextProcessor
| Parameter | Default | Notes |
|-----------|---------|-------|
| `common_element_threshold` | 0.2 | Fraction of pages a text block must appear on to be suppressed. 0.15 catches more running headers. |
| `common_element_min_blocks` | 3 | Minimum occurrences before suppression. |
| `max_streak` | 3 | Max consecutive pages before always suppressing. |
| `text_match_threshold` | 90 | Fuzzy match score (0-100) for similarity. 85 catches slight variations. |

### TextProcessor
| Parameter | Default | Notes |
|-----------|---------|-------|
| `column_gap_ratio` | 0.02 | Minimum page-width fraction for a column gap. Increase to 0.06 to better join 2-column text (fixes hyphenation artifacts like "wor-" / "ship"). |

### ListProcessor
| Parameter | Default | Notes |
|-----------|---------|-------|
| `min_x_indent` | 0.01 | Indentation threshold for nested list items. |

### BlockRelabelProcessor
| Parameter | Default | Notes |
|-----------|---------|-------|
| `block_relabel_str` | `""` | Comma-separated rules: `"SectionHeader:Text:0.6"` demotes low-confidence headings to body text before KMeans runs. Critical for reducing spurious H1s. Format: `original:new:confidence_threshold`. |

### DocumentBuilder
| Parameter | Default | Notes |
|-----------|---------|-------|
| `lowres_image_dpi` | 96 | DPI for layout detection images. 72 is fine for CPU inference and reduces RAM. |
| `highres_image_dpi` | 192 | DPI for OCR images. Irrelevant when `disable_ocr=True`. |
| `disable_ocr` | False | Set True for PDFs with embedded text. Skips OCR entirely. |

### PdfProvider
| Parameter | Default | Notes |
|-----------|---------|-------|
| `pdftext_workers` | 4 | Parallel workers for PDF text extraction. Set 1 for Cloud Run. |
| `disable_links` | False | Strip hyperlink annotations. Set True to reduce text fragmentation. |
| `flatten_pdf` | True | Flatten PDF structure before processing. |

### MarkdownRenderer
| Parameter | Default | Notes |
|-----------|---------|-------|
| `page_separator` | `"---...---"` | Text inserted between pages when `paginate_output=True`. |
| `html_tables_in_markdown` | False | Output tables as HTML instead of Markdown. |

### Other flags (passed directly to config dict)
| Key | Notes |
|-----|-------|
| `disable_image_extraction` | Suppress image extraction to output directory |
| `extract_images` | Belt-and-suspenders image suppression |
| `page_range` | List of 0-indexed page numbers to convert. e.g. `list(range(62, 200))` |

---

## Marker Config Iteration Log

### Iteration 1 — Baseline
```python
{"level_count": 6, "default_level": 3, "disable_ocr": True,
 "pdftext_workers": 1, "DocumentBuilder_lowres_image_dpi": 72,
 "disable_image_extraction": True}
```
**Results:** H1=73, H2=2, H3=3, H4=25. Images in output (21 refs). Blockquotes=0. Lists=50/66.
**Problems:** `level_count=6` causes KMeans to over-cluster, most headings become H1.

### Iteration 2
Added: `level_count=4`, `BlockquoteProcessor_min_x_indent=0.03`, `extract_images=False`
**Results:** H1=73 (unchanged). Blockquotes=2 (slight improvement). Images=0 (fixed).
**Problems:** Heading over-assignment unchanged. level_count alone doesn't fix the H1 problem.

### Iteration 3 (current)
Added: `block_relabel_str="SectionHeader:Text:0.6"`, `merge_threshold=0.4`,
`level_count=3`, `BlockquoteProcessor_min_x_indent=0.01`,
`BlockquoteProcessor_x_start_tolerance=0.05`, `BlockquoteProcessor_x_end_tolerance=0.05`,
`TextProcessor_column_gap_ratio=0.06`, `disable_links=True`
**Key hypothesis:** `block_relabel_str` demotes low-confidence layout headings before KMeans
runs, reducing the spurious H1 count. Results pending.

---

## Marker Output Quality — Known Issues

After 3 config iterations, here is the current state of each output element vs the reference:

### Working well ✓
- Body text paragraph joining — correct, no line-by-line fragmentation
- Inline bold/italic — `**As priests...**`, `*most holy work*` correct
- Numbered and bullet lists — ~50/66 items correct
- Running header suppression — "INTRODUCTION SESSION ONE" removed
- Image references — removed via post-processing

### Partially working
- Blockquotes — 2/23 detected. Marker's spatial indentation detector struggles with 8pt
  scripture quotes which have subtle indentation in this PDF's 2-column layout.
- Lists — `- 1. Question` format instead of `1. Question` (Marker combining bullet + number markers)

### Not working / requires post-processing
- **Heading hierarchy** — 73 H1s vs 1 expected. Root cause: Marker's layout model classifies
  too many blocks as SectionHeader, then KMeans can't find clean clusters. Explored knobs:
  `level_count`, `merge_threshold`, `block_relabel_str`. May ultimately need font-size-based
  post-processing using PyMuPDF span data.
- **Citations** — `<<` format not produced. Marker has no concept of right-aligned citation.
  Fix: post-processing regex to detect short standalone scripture reference lines.
- **Hyphenation artifacts** — "wor-" / "ship" splits from 2-column layout. `column_gap_ratio`
  tuning may help. Fix: post-processing regex to merge lines ending with hyphen.
- **Pull-quote callouts** — appear as orphan paragraphs mid-text AND again in body text.
  Fix: detect and remove duplicate standalone callout paragraphs in post-processing.
- **Verse numbers in Psalm 103** — inconsistent: some `**103:1**` (bold), some `<sup>2</sup>`.
  Fix: post-processing to normalize all verse numbers to `<sup>N</sup>`.

---

## Future Config Ideas to Try

These are untried Marker configuration approaches worth attempting in future sessions:

**1. `force_layout_block = "Text"`**
Set on `LayoutBuilder` to bypass layout detection entirely and treat every block as text.
For prose-only books this could eliminate all heading mis-classification. Downside: no
headings detected at all — would need full post-processing pass to assign headings.
```python
config["force_layout_block"] = "Text"
```

**2. More aggressive `block_relabel_str` threshold**
Try 0.5 or even 0.4 (lower = demote more SectionHeaders to Text). Goal: only keep
headings the layout model is very confident about, reducing KMeans input noise.
```python
config["block_relabel_str"] = "SectionHeader:Text:0.5"
```

**3. `level_count=2` — just two heading sizes**
Force KMeans to find only 2 clusters: "big" (session/movement titles) and "small"
(section headings). Everything else falls to `default_level`. Simplest possible clustering.

**4. LLM-assisted section header detection**
Add `LLMSectionHeaderProcessor` back into the processor list with a Gemini API key.
This uses an LLM to re-examine ambiguous heading blocks and assign better levels.
Potentially the most accurate fix for the heading hierarchy problem.
```python
# Requires: pip install google-genai + GEMINI_API_KEY env var
processor_list.append("marker.processors.llm.llm_sectionheader.LLMSectionHeaderProcessor")
config["use_llm"] = True
config["llm_service"] = "marker.services.gemini.GoogleGeminiService"
```

**5. Custom `BaseProcessor` for font-size-based heading assignment**
After Marker runs, add a custom processor that reads span font sizes from the document
and reassigns `heading_level` based on the known font map:
- 20pt Regular → level 1
- 20pt Bold → level 3
- 14pt Bold → level 4
- etc.
This is the most reliable fix but requires custom code.

**6. Post-processing pipeline (minimal custom code)**
Rather than fighting Marker's heading detection, accept its output and apply a thin
post-processing layer using PyMuPDF to re-read font sizes for the heading blocks.
Priority order for fixes:
1. Citation detection regex (easy, high value)
2. Hyphenation artifact repair (easy)
3. Bullet+number list fix: `- 1.` → `1.` (one regex)
4. Font-size heading remapping via PyMuPDF (moderate, high value)
5. Blockquote detection via font size (moderate)

**7. `paginate_output=True` for page-aware processing**
Enable pagination markers between pages, then use them in post-processing to apply
per-page context (e.g. which session we're in) for smarter heading assignment.

---

## Infrastructure

### Cloud Run + Marker: Key Lessons

**Models must load BEFORE uvicorn starts.** If models load in a background thread after
the server starts, Cloud Run will scale the instance to zero while models are loading
(typically after 60-90 seconds of no successful responses). The fix: load models
synchronously in `__main__` before calling `uvicorn.run()`. The port stays closed
until models are ready; Cloud Run gen2 waits up to 240 seconds for the port to open.

**Do NOT free unused models.** Even with `disable_ocr=True` and table/LLM processors
removed, Marker accesses all 5 model objects internally during the pipeline. Setting
any model to `None` causes `AttributeError: 'NoneType' has no attribute 'disable_tqdm'`.
All 5 must stay loaded.

**Surya's model cache location.** Surya downloads models to `/root/.cache/datalab/models/`
NOT to `HF_HOME` or `TRANSFORMERS_CACHE`. Any GCS caching strategy must target this path.

**Base image approach for cold starts.** The `Dockerfile.base` + `cloudbuild-base.yaml`
pattern bakes models into a base Docker image. The app `Dockerfile` then does
`FROM marker-pdf-base:latest` + `COPY . /app/` — builds in ~30 seconds, cold starts
in ~30 seconds (model loading from disk, no download). Build the base image once with:
```bash
cd /c/Users/Steve/Affinity-to-Markdown/marker-pdf
gcloud builds submit . --config cloudbuild-base.yaml --project affinity-markdown-converter --timeout 3600
```
Rebuild base only when upgrading `marker-pdf` version or adding pip dependencies.

**Cloud Build timeout.** `gcloud run deploy --source` has an implicit Cloud Build timeout
of ~10 minutes. A vanilla `pip install marker-pdf` (PyTorch + Surya) takes 15+ minutes.
Solution: install CPU-only torch first (`--index-url https://download.pytorch.org/whl/cpu`),
cutting download from ~2GB to ~200MB. Or use the base image approach above.

**Signal 11 (SIGSEGV) crashes.** Seen during model loading when all 5 models try to
load simultaneously into an 8GB container. Using the base image + synchronous loading
(models load one at a time sequentially) resolves this.

### Docker Image Strategy

```
marker-pdf-base (built once manually, ~20 min)
  └── python:3.11-slim + system libs
  └── pip install torch (CPU) + marker-pdf + all deps
  └── create_model_dict() → downloads ~3GB Surya models to /root/.cache/datalab/models/

marker-pdf-converter (CI build, ~30 sec)
  FROM marker-pdf-base    ← already has everything
  COPY . /app/            ← just copies app code
```

### Cloud Run Configuration

| Setting | afpub-converter | marker-pdf-converter |
|---------|----------------|---------------------|
| Memory | 2 GB | 8 GB |
| CPU | default | 4 |
| Timeout | 300s | 600s |
| Concurrency | default | 2 |
| Min instances | 0 | 0 |
| Max instances | default | 3 |
| Execution env | gen2 | gen2 |
| Startup | normal | synchronous model load before port opens |

### GCS File Routing

Files >30 MB exceed Cloud Run's HTTP body limit. Routing:

- `POST /api/request-upload` → returns a signed V4 PUT URL for GCS
- Browser uploads directly to GCS via XHR
- `POST /convert-from-gcs` → Cloud Run downloads from GCS, converts, deletes
- `xhr.onerror` on browser side → resolve (not reject): CORS headers can block the response even when the upload succeeded

### Secrets

- `GCP_SA_KEY` — GitHub Actions secret (JSON, for deploy authentication)
- `GCP_SA_KEY_B64` — Cloud Run env var (base64-encoded JSON, for GCS operations at runtime)
- Secret Manager API was NOT enabled in this project — pass `GCP_SA_KEY_B64` as a plain
  env var via GitHub Actions `env_vars`, not via `secrets:` in the workflow.

---

## Local CLI Usage (Recommended for Quality Testing)

Marker is not designed for serverless. For iterating on output quality, run locally:

**Setup (one time):**
```bash
cd /c/Users/Steve/Affinity-to-Markdown/marker-pdf
/c/Users/Steve/AppData/Local/Programs/Python/Python311/python.exe -m venv venv311
source venv311/Scripts/activate
pip install marker-pdf==1.10.2
```
Note: Requires Python 3.11 — Marker is not compatible with Python 3.14 (Pillow and
regex packages lack prebuilt wheels).

**Convert a PDF:**
```bash
source venv311/Scripts/activate   # activate each session
python run.py "C:/path/to/book.pdf"
python run.py "C:/path/to/book.pdf" --page-range 62-200
```

**Iteration workflow:**
1. Claude pushes updated config to `marker-pdf/run.py`
2. `git pull` in Git Bash
3. `python run.py "C:/path/to/Session1_extract.pdf"`
4. Upload output `.md` to Claude
5. Claude diffs vs reference, identifies issues, updates config

Models download on first run (~5-10 min), then load from disk in ~30 seconds on every
subsequent run. Models stored at `~/.cache/datalab/models/` permanently.

---

## File Structure

```
/                               ← afpub-converter service root
  afpub_to_markdown.py          ← AFPUB binary parser (v0.10, stable)
  main.py                       ← FastAPI: afpub + pdf endpoints
  pdf_to_markdown.py            ← PyMuPDF PDF extractor (fallback, not primary)
  static/index.html             ← Web UI with format toggle
  templates/
    homestead/
      styles.yaml               ← AFPUB style ID → Markdown mappings
      pdf_styles.yaml           ← PyMuPDF font → Markdown mappings (fallback)
  .github/workflows/
    deploy.yml                  ← Fires only on root service file changes
    deploy-marker.yml           ← Fires only on marker-pdf/** changes

marker-pdf/                     ← marker-pdf-converter service root + local CLI
  Dockerfile                    ← FROM marker-pdf-base; COPY app code only
  Dockerfile.base               ← Full build: system libs + pip + Surya models
  cloudbuild-base.yaml          ← One-time manual base image build config
  requirements.txt
  app.py                        ← FastAPI routing (loads models before starting)
  converter.py                  ← Marker conversion logic + CLI __main__
  model_loader.py               ← Synchronous model loading singleton
  model_cache.py                ← GCS model cache (restore/save) — not yet wired
  run.py                        ← Simple local runner (recommended for iteration)
```

---

## Session Log

| Date | What was done |
|------|--------------|
| Mar 2026 | AFPUB binary parser reached v0.10 — all Session 1 features working |
| Mar 2026 | Switched strategy to PDF extraction — AFPUB fragility acknowledged |
| Mar 2026 | Evaluated PyMuPDF (too manual), Docling (OOM), Marker (selected) |
| Mar 2026 | Deep-dived Homestead PDF font structure — complete font→role mapping |
| Mar 2026 | Marker service infrastructure: base image, synchronous loading, 35-second cold start |
| Mar 2026 | First successful local conversion via `run.py` on Python 3.11 venv |
| Mar 2026 | Config iterations 1-3: heading detection, blockquotes, column joining, block relabeling |
| Apr 2026 | Iteration 3 in progress — `block_relabel_str` is the key untested lever for H1 problem |
