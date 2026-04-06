# Cloud Run Web App (Archived)

This was the Phase 2 approach: a web-based converter deployed to Google Cloud Run.

**Status:** Superseded by the desktop app + marker-pdf pipeline.

**Why it was superseded:** The desktop app provides a much better user experience (progress tracking, template selection, no upload size limits) and the marker-pdf pipeline produces significantly higher quality output than the web app's converter.

## Files

- `main.py` — FastAPI server with file upload endpoint
- `pdf_to_markdown.py` — Early PDF-to-Markdown conversion (pre-Marker)
- `Dockerfile` — Container config for Cloud Run
- `requirements.txt` — Python dependencies
- `static/index.html` — Browser-based upload UI
- `deploy.yml` — GitHub Actions workflow (deployed to `afpub-converter` Cloud Run service)

## Infrastructure (now inactive)

- GCP project: `affinity-markdown-converter`
- Service: `afpub-converter` (us-east1)
- The GitHub Actions workflow (`deploy.yml`) triggered on push to main.
