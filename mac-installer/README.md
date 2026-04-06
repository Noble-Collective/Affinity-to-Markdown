# Affinity-PDF-Markdown Converter — macOS

macOS desktop app for the PDF-to-Markdown conversion pipeline. Code-signed and notarized by Apple — installs cleanly with zero Gatekeeper warnings.

## Installing

Download the latest `Affinity-PDF-Markdown-Converter-*.dmg` from [GitHub Actions](../../actions/workflows/build-installers.yml) (click the latest green run → Artifacts → macOS-Installer). Open the DMG, drag the app to Applications.

## Using the App

Same interface as the Windows version:

1. **Select a PDF** — Browse to the book PDF
2. **Choose a template** — Defaults to `homestead`
3. **Pick output path** — Auto-filled based on PDF name
4. **Choose mode:**
   - **Full Conversion** — Marker ML + post-processing (~10-15 min on CPU)
   - **Post-process Only** — From existing `.raw.md` (~2 seconds)
5. **Click Convert** — Watch per-page Marker progress in the log pane

### Automatic Updates

The app checks for pipeline updates every 30 seconds. When available, a green banner appears. Click **Update Now** — 2 seconds, no reinstall. Fails silently if offline.

## Building the Installer

### Cloud Build (recommended)

Go to [Actions → Build Installers](../../actions/workflows/build-installers.yml) → Run workflow. The Mac build automatically:
- Bundles Python + all dependencies via PyInstaller
- Signs the `.app` with a Developer ID Application certificate
- Creates the `.dmg` with an Applications shortcut
- Submits to Apple for notarization
- Staples the notarization ticket

The signing certificate and Apple credentials are stored as GitHub repository secrets. No Mac needed to build.

### Local Build (alternative)

Requires a Mac with Python 3.11 and Xcode CLI tools:

```bash
cd mac-installer
chmod +x build.sh
./build.sh
```

Note: local builds are **not** code-signed unless you manually run `codesign` and `notarytool`.

## Architecture

Same Python code as Windows — `main.py`, `gui.py`, `pipeline.py`, `config.py`, `updater.py` are identical. Only build scripts and spec files differ.

```
mac-installer/
  main.py, gui.py, pipeline.py, config.py, updater.py   # Shared code
  affinity_converter_mac.spec      # macOS PyInstaller spec (.app bundle)
  build.sh                         # Local build script
  requirements.txt                 # Python dependencies
```

### Code Signing Setup

Code signing is fully automated in the GitHub Actions cloud build. The following repository secrets are required:

| Secret | Purpose |
|--------|--------|
| `APPLE_CERTIFICATE_BASE64` | Developer ID Application certificate (.p12, base64-encoded) |
| `APPLE_CERTIFICATE_PASSWORD` | Password for the .p12 file |
| `APPLE_TEAM_ID` | Apple Developer Team ID (10-character string) |
| `APPLE_ID` | Apple ID email for notarization |
| `APPLE_ID_PASSWORD` | App-specific password for notarization |

These are already configured for this repo.

### Apple Silicon vs Intel

The GitHub Actions runner (`macos-latest`) builds for Apple Silicon. PyTorch auto-selects the correct wheels for the build architecture.
