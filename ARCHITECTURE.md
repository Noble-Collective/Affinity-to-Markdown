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
- Fallback: all-caps block with mixed sizes → skip

**Verse labels are drop-cap + small-caps too:**
- "VERSE 4" = Bold 10pt "V" + Bold 7pt "ERSE" + Bold 10pt "4"
- The 7pt span is the distinctive marker
- Should map to H6 via Marker's SectionHeaderProcessor

**Blockquotes and citations are the same font/size (8pt Regular):**
- Long blocks (≥100 chars) = blockquote `>`
- Short blocks (<100 chars) = citation `<<`
- Affinity Publisher renders overview section quotes in 8pt, not the larger italic size

**The whole-book PDF is 481 pages.** The first ~60 pages are front matter (title pages, copyright, series info, table of contents). Session 1 starts around page 63. Marker's `page_range` config option lets us skip front matter.

---

## Marker Configuration Reference

### How Config Works

Config is passed as a plain dict to `PdfConverter`. Keys map to processor attributes directly, or use prefixed keys for processor-specific settings:

```python
config = {
    "level_count": 6,                          # sets SectionHeaderProcessor.level_count
    "SectionHeaderProcessor_level_count": 6,   # same, more explicit
}
```

The `assign_config()` utility applies matching keys to processor instances at init time.

### Recommended Config for Noble Collective Books

```python
config = {
    # ── Heading levels ──────────────────────────────────────────────
    # Default is 4 (H1-H4). We need 6 for verse labels (H6).
    "level_count": 6,
    # Unclustered headers default to H3, not H2
    "default_level": 3,

    # ── Running header removal ───────────────────────────────────────
    # Catch text appearing on 15%+ of pages (default: 0.2 = 20%)
    "common_element_threshold": 0.15,
    # Slightly looser fuzzy matching (default: 90)
    "text_match_threshold": 85,

    # ── Performance ─────────────────────────────────────────────────
    # PDF has embedded text — no OCR needed
    "disable_ocr": True,
    # Single worker for Cloud Run
    "pdftext_workers": 1,
    # Lower DPI for layout detection (no GPU, CPU inference)
    "DocumentBuilder_lowres_image_dpi": 72,
    # No images in output
    "disable_image_extraction": True,

    # ── Page range ───────────────────────────────────────────────────
    # Skip front matter. Homestead Session 1 starts at page ~63 (0-indexed: 62).
    # Pass as a list of ints: list(range(62, 200))
    # Leave as None to convert the whole document.
    # "page_range": list(range(62, 200)),
}
```

### Trimmed Processor List

Remove all LLM and irrelevant processors for a prose book:

```python
from marker.processors.order import OrderProcessor
from marker.processors.block_relabel import BlockRelabelProcessor
from marker.processors.line_merge import LineMergeProcessor
from marker.processors.blockquote import BlockquoteProcessor
from marker.processors.ignoretext import IgnoreTextProcessor
from marker.processors.list import ListProcessor
from marker.processors.page_header import PageHeaderProcessor
from marker.processors.sectionheader import SectionHeaderProcessor
from marker.processors.text import TextProcessor
from marker.processors.blank_page import BlankPageProcessor

PROCESSOR_LIST = [
    OrderProcessor,
    BlockRelabelProcessor,
    LineMergeProcessor,
    BlockquoteProcessor,
    IgnoreTextProcessor,
    ListProcessor,
    PageHeaderProcessor,
    SectionHeaderProcessor,
    TextProcessor,
    BlankPageProcessor,
]
```

**Removed (not needed for prose books):**
- All 10 `LLM*` processors (LLMSectionHeaderProcessor, LLMTableProcessor, etc.)
- `CodeProcessor`, `EquationProcessor`, `FootnoteProcessor`
- `TableProcessor`, `LLMTableMergeProcessor`, `LLMFormProcessor`
- `LineNumbersProcessor`, `ReferenceProcessor`, `DebugProcessor`

### BlockTypes Available for Custom Processors

If we need a custom `BaseProcessor`, these are the available block types:

```
Text, SectionHeader, ListGroup, ListItem, PageHeader, PageFooter,
Table, TableCell, TableGroup, Figure, FigureGroup, Picture, PictureGroup,
Caption, Footnote, Code, Equation, Form, Handwriting, TextInlineMath,
TableOfContents, Reference, ComplexRegion, Line, Span, Char, Page, Document
```

### Custom Processor Pattern

Only use this after exhausting Marker's built-in configuration. A custom processor has full access to the structured document object:

```python
from marker.processors import BaseProcessor
from marker.schema import BlockTypes
from marker.schema.document import Document

class NobleCollectiveProcessor(BaseProcessor):
    """Book-specific cleanup that can't be handled by config alone."""
    block_types = (BlockTypes.Text, BlockTypes.SectionHeader)

    def __call__(self, document: Document):
        for page in document.pages:
            for block in page.contained_blocks(document, self.block_types):
                # Example: suppress a block
                block.ignore_for_output = True
                # Example: change a block's type
                block.block_type = BlockTypes.Text
                # Example: modify content
                # (access via block.structure → line IDs → document lookup)
```

Inject it into the pipeline by appending to `PROCESSOR_LIST` before `TextProcessor`.

---

## Infrastructure

### Docker Image Strategy

The Marker Docker image bakes in ~3 GB of Surya model weights at build time to avoid cold-start downloads on Cloud Run. Models are cached at `/app/models` with these env vars:

```
HF_HOME=/app/models
TORCH_HOME=/app/models/torch
TRANSFORMERS_CACHE=/app/models/transformers
```

These must match at runtime so the app finds the pre-downloaded weights.

**Build time:** ~15-20 minutes on first build (model download). Subsequent builds that only change app code are ~2 minutes (Docker layer cache).

**Layer cache invalidation:**
- Change `requirements.txt` → pip install re-runs → slow
- Change `download_models.py` → models re-download → slow
- Change `app.py`, `converter.py`, `gcs_client.py` → only `COPY . .` re-runs → fast

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

### GCS File Routing

Files >30 MB exceed Cloud Run's HTTP body limit. Routing:

- `POST /api/request-upload` → returns a signed V4 PUT URL for GCS
- Browser uploads directly to GCS via XHR
- `POST /convert-from-gcs` → Cloud Run downloads from GCS, converts, deletes
- `xhr.onerror` on browser side → resolve (not reject): CORS headers can block the response even when the upload succeeded; GCS download confirms actual arrival

### Secrets

- `GCP_SA_KEY` — GitHub Actions secret (JSON, for deploy authentication)
- `GCP_SA_KEY_B64` — Cloud Run env var (base64-encoded JSON, for GCS operations at runtime)

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
    deploy.yml                  ← Auto-deploys root → afpub-converter on any push
    deploy-marker.yml           ← Auto-deploys marker-pdf/ → marker-pdf-converter
                                   only when marker-pdf/** changes

marker-pdf/                     ← marker-pdf-converter service root
  Dockerfile                    ← Bakes Surya models into image
  requirements.txt
  download_models.py            ← Runs during Docker build to pre-cache models
  app.py                        ← FastAPI routing only
  converter.py                  ← Marker conversion logic (chunk 2)
  gcs_client.py                 ← GCS operations (chunk 3)
```

---

## Known Issues & Decisions

**Affinity Publisher doesn't store a name→ID mapping in the binary.** The same style name can have different IDs across different book templates. Each new book template requires running `--analyze-styles` on a sample file and manually updating `styles.yaml`. This is a fundamental limitation of the AFPUB format, not a fixable bug.

**Marker requires 8 GB RAM.** The 5 Surya models (layout, recognition, detection, table rec, OCR error) load into memory simultaneously. There is no lightweight text-only mode — even `disable_ocr=True` still loads the layout model for structural understanding.

**The Homestead PDF is 481 pages.** Use `page_range` to target specific sessions. Front matter ends around page 62. Each session is roughly 50-80 pages.

**Signed URLs vs Resumable Sessions for GCS uploads.** Resumable session URLs fail for browser uploads due to CORS. V4 signed PUT URLs work. This is a known GCS limitation, not a bug in our code.

---

## Session Log

| Date | What was done |
|------|--------------|
| Mar 2026 | AFPUB binary parser reached v0.10 — all Session 1 features working |
| Mar 2026 | Switched strategy to PDF extraction — AFPUB fragility acknowledged |
| Mar 2026 | Evaluated PyMuPDF (too manual), Docling (OOM), Marker (selected) |
| Mar 2026 | Deep-dived Homestead PDF font structure — complete font→role mapping documented above |
| Mar 2026 | Marker service chunk 1 deployed: Dockerfile + health check + model pre-download |
| Mar 2026 | Chunk 2 pending: converter.py with trimmed processor list and config tuning |
