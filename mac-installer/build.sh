#!/bin/bash
# build.sh — Build the Affinity-PDF-Markdown Converter for macOS
#
# Prerequisites:
#   - Python 3.11 installed (python3.11 or python3)
#   - Xcode command line tools: xcode-select --install
#   - Run from the mac-installer/ directory
#
# Output: dist/Affinity-PDF-Markdown-Converter-0.1.0.dmg

set -e

APP_NAME="Affinity-PDF-Markdown Converter"
DMG_NAME="Affinity-PDF-Markdown-Converter"
VERSION="0.1.0"

echo ""
echo "============================================"
echo "  ${APP_NAME} — macOS Build"
echo "============================================"
echo ""

if [ ! -f "main.py" ]; then
    echo "ERROR: Run this script from the mac-installer directory."
    exit 1
fi

# Find Python 3.11
PYTHON=""
for candidate in python3.11 python3 python; do
    if command -v "$candidate" &>/dev/null; then
        ver=$("$candidate" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
        if [ "$ver" = "3.11" ]; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "WARNING: Python 3.11 not found. Trying python3..."
    PYTHON="python3"
    echo "Using: $($PYTHON --version 2>&1)"
fi

# Create/activate venv
VENV_DIR="venv311"
if [ ! -d "$VENV_DIR" ]; then
    echo "[1/5] Creating Python venv..."
    "$PYTHON" -m venv "$VENV_DIR"
else
    echo "[1/5] Using existing venv..."
fi
source "$VENV_DIR/bin/activate"
echo "  Python: $(python3 --version)"

# Install dependencies
echo ""
echo "[2/5] Installing dependencies (may take a while on first run)..."
pip install --upgrade pip wheel setuptools -q
pip install torch -q
pip install marker-pdf==1.10.2 pymupdf pyyaml -q
pip install "pyinstaller>=6.0" -q
echo "  Dependencies installed."

# Verify PyInstaller
echo ""
echo "[3/5] Verifying PyInstaller..."
pyinstaller --version

# Run PyInstaller
echo ""
echo "[4/5] Running PyInstaller (this takes several minutes)..."
pyinstaller affinity_converter_mac.spec --noconfirm

if [ ! -d "dist/${APP_NAME}.app" ]; then
    echo "ERROR: PyInstaller did not produce the expected .app bundle."
    exit 1
fi
echo "PyInstaller complete: dist/${APP_NAME}.app"

# Create DMG
echo ""
echo "[5/5] Creating DMG installer..."
DMG_DIR="dist/dmg-staging"
DMG_PATH="dist/${DMG_NAME}-${VERSION}.dmg"
rm -rf "$DMG_DIR" && rm -f "$DMG_PATH"
mkdir -p "$DMG_DIR"
cp -R "dist/${APP_NAME}.app" "$DMG_DIR/"
ln -s /Applications "$DMG_DIR/Applications"
hdiutil create -volname "$APP_NAME" -srcfolder "$DMG_DIR" -ov -format UDZO "$DMG_PATH"
rm -rf "$DMG_DIR"

echo ""
echo "============================================"
echo "  BUILD COMPLETE"
echo "============================================"
echo ""
echo "  App: dist/${APP_NAME}.app"
echo "  DMG: ${DMG_PATH}"
echo ""
echo "  NOTE: macOS Gatekeeper may block unsigned apps."
echo "  Right-click > Open to bypass, or code-sign for distribution."
echo ""
