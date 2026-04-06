#!/bin/bash
# ============================================================================
#  cleanup.sh — One-time repo restructure script
#
#  Run this ONCE from the repo root to move archived files into archive/
#  and clean up obsolete files. Uses `git mv` to preserve history.
#
#  Usage:
#    cd ~/Affinity-to-Markdown
#    git pull --rebase
#    chmod +x cleanup.sh
#    ./cleanup.sh
# ============================================================================

set -e

echo ""
echo "============================================"
echo "  Repo Restructure — One-Time Cleanup"
echo "============================================"
echo ""

# Verify we're in the repo root
if [ ! -d "marker-pdf" ] || [ ! -d "windows-installer" ]; then
    echo "ERROR: Run this from the Affinity-to-Markdown repo root."
    exit 1
fi

# Check for uncommitted changes
if ! git diff --quiet HEAD 2>/dev/null; then
    echo "ERROR: You have uncommitted changes. Commit or stash them first."
    echo "  git stash"
    echo "  ./cleanup.sh"
    echo "  git stash pop"
    exit 1
fi

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
  - deploy.yml (web app CI/CD workflow)
  - ARCHITECTURE.md, BUILD.md (old docs)

Removed:
  - windows-installer/homestead_converter.spec (replaced by affinity_converter_win.spec)

Active project structure:
  - marker-pdf/           Core pipeline
  - windows-installer/    Windows desktop app
  - mac-installer/        macOS desktop app
  - .github/workflows/    deploy-marker.yml (manual trigger)"

echo ""
git push

echo ""
echo "============================================"
echo "  Restructure Complete"
echo "============================================"
echo ""
echo "Repo structure:"
echo "  marker-pdf/          ← Core pipeline"
echo "  windows-installer/   ← Windows app + build"
echo "  mac-installer/       ← macOS app + build"
echo "  archive/             ← Retired code"
echo "  .github/workflows/   ← CI/CD"
echo ""
echo "You can delete this script now:"
echo "  git rm cleanup.sh && git commit -m 'Remove cleanup script' && git push"
echo ""
