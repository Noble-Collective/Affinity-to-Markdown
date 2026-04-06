# Archive — Retired Code

This directory contains code from earlier phases of the project that is no longer actively used. It is preserved for reference and historical context.

## Contents

### `afpub-converter/`

**Phase 1: Direct .afpub binary parsing** (abandoned March 2026)

Attempted to extract text directly from Affinity Publisher's proprietary `.afpub` binary format by reverse-engineering the zstd-compressed payload. Worked for Session 1 of the HomeStead book but was too fragile for production use — Affinity's format changes between versions and the binary structures are undocumented.

Key files:
- `afpub_to_markdown.py` — The extractor script (~72KB, 1800+ lines)
- `styles.yaml` — Style ID mappings for the HomeStead book template

### `web-app/`

**Phase 2: Cloud Run web application** (superseded April 2026)

A FastAPI web app deployed to Google Cloud Run that accepted `.afpub` file uploads and returned converted Markdown. Superseded by the PDF-based pipeline (`marker-pdf/`) which produces significantly better output.

Key files:
- `main.py` — FastAPI web server
- `pdf_to_markdown.py` — Early PDF conversion attempt
- `Dockerfile` — Cloud Run container config
- `static/index.html` — Upload UI
- `deploy.yml` — GitHub Actions workflow for Cloud Run deployment

### Root-level archived files

- `ARCHITECTURE.md` — Architecture docs for the .afpub converter phase
- `BUILD.md` — Build instructions for the Cloud Run web app
