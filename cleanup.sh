#!/bin/bash
# One-time repo restructure — moves archived files, cleans up obsolete files.
# Run from repo root: chmod +x cleanup.sh && ./cleanup.sh

set -e
echo ""
echo "=== Repo Restructure ==="
echo ""

if [ ! -d "marker-pdf" ]; then echo "ERROR: Run from repo root."; exit 1; fi

echo "[1/4] Moving .afpub converter to archive..."
mkdir -p archive/afpub-converter
git mv afpub_to_markdown.py archive/afpub-converter/ 2>/dev/null || true

echo "[2/4] Moving web app to archive..."
mkdir -p archive/web-app
git mv main.py archive/web-app/ 2>/dev/null || true
git mv pdf_to_markdown.py archive/web-app/ 2>/dev/null || true
git mv Dockerfile archive/web-app/ 2>/dev/null || true
git mv requirements.txt archive/web-app/ 2>/dev/null || true
git mv static archive/web-app/ 2>/dev/null || true
git mv templates archive/web-app/ 2>/dev/null || true
git mv ARCHITECTURE.md archive/ 2>/dev/null || true
git mv BUILD.md archive/ 2>/dev/null || true
git mv .github/workflows/deploy.yml archive/web-app/ 2>/dev/null || true

echo "[3/4] Removing obsolete files..."
git rm windows-installer/homestead_converter.spec 2>/dev/null || true

echo "[4/4] Committing..."
git add -A
git commit -m "Restructure repo: archive retired code, clean root

Moved to archive/afpub-converter/:
  - afpub_to_markdown.py (Phase 1 binary parser)

Moved to archive/web-app/:
  - main.py, pdf_to_markdown.py, Dockerfile (Cloud Run web app)
  - requirements.txt, static/, templates/ (web app assets)
  - deploy.yml, ARCHITECTURE.md, BUILD.md

Removed:
  - windows-installer/homestead_converter.spec (replaced)"

git push

echo ""
echo "=== Done ==="
echo "Active: marker-pdf/ windows-installer/ mac-installer/"
echo "Archived: archive/"
echo ""
echo "You can now delete this script:"
echo "  git rm cleanup.sh && git commit -m 'Remove cleanup script' && git push"
