# Affinity-PDF-Markdown Converter — macOS

macOS desktop app for the PDF-to-Markdown conversion pipeline.

## Quick Start (Development)

```bash
cd mac-installer
source ../marker-pdf/venv311/bin/activate
python main.py
```

## Building the macOS App + DMG

```bash
cd mac-installer
chmod +x build.sh
./build.sh
```

Produces:
- `dist/Affinity-PDF-Markdown Converter.app`
- `dist/Affinity-PDF-Markdown-Converter-0.1.0.dmg`

The DMG contains the app + an Applications shortcut. Standard drag-to-install.

## Code Signing (for distribution)

Without signing, Gatekeeper blocks the app. Users can right-click > Open to bypass.

For production:
```bash
codesign --deep --force --sign "Developer ID Application: Name (TEAMID)" \
    "dist/Affinity-PDF-Markdown Converter.app"

xcrun notarytool submit dist/Affinity-PDF-Markdown-Converter-0.1.0.dmg \
    --apple-id you@email.com --team-id TEAMID \
    --password @keychain:notarytool-password --wait

xcrun stapler staple dist/Affinity-PDF-Markdown-Converter-0.1.0.dmg
```

## Architecture

Same Python code as Windows — `main.py`, `gui.py`, `pipeline.py`, `config.py` are identical. Only build scripts and spec files differ.

```
mac-installer/
  main.py, gui.py, pipeline.py, config.py   # Shared code
  affinity_converter_mac.spec                # macOS PyInstaller spec
  build.sh                                   # Build script (venv + .app + .dmg)
```

### Apple Silicon vs Intel

PyTorch auto-selects the correct wheels. Build on the target architecture. Separate builds are easier than universal binaries.

## Prerequisites

- Python 3.11 — `brew install python@3.11`
- Xcode CLI tools — `xcode-select --install`
- ~4GB disk space for venv + build output
