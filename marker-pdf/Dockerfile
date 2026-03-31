# ── Marker PDF → Markdown conversion service ────────────────────────────────
# Builds on the pre-built base image which contains:
#   - system libraries
#   - all pip dependencies (torch CPU, marker-pdf, fastapi, etc.)
#   - Surya model weights (~3 GB) baked in at /root/.cache/datalab/models/
#
# The base image is built ONCE manually via:
#   gcloud builds submit marker-pdf \
#     --config marker-pdf/cloudbuild-base.yaml \
#     --project affinity-markdown-converter --timeout 3600
#
# Rebuild the base only when: upgrading marker-pdf, adding packages,
# or updating Surya models.

FROM us-east1-docker.pkg.dev/affinity-markdown-converter/cloud-run-source-deploy/marker-pdf-base:latest

# Application code only — no pip install, no model download
COPY . /app/

WORKDIR /app

ENV PORT=8080
EXPOSE 8080

CMD ["python", "app.py"]
