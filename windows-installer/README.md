# Affinity-PDF-Markdown Converter — Windows

Windows desktop app for the PDF-to-Markdown conversion pipeline.

## Installing

Download the latest `Affinity-PDF-Markdown-Converter_Setup.exe` from [GitHub Actions](../../actions/workflows/build-installers.yml) (click the latest green run → Artifacts → Windows-Installer). Run the installer — it installs to Program Files with Start Menu shortcuts.

## Using the App

1. **Select a PDF** — Browse to the book PDF
2. **Choose a template** — Defaults to `homestead`
3. **Pick output path** — Auto-filled based on PDF name
4. **Choose mode:**
   - **Full Conversion** — Marker ML + post-processing (~10-15 min on CPU)
   - **Post-process Only** — From existing `.raw.md` (~2 seconds)
5. **Click Convert** — Watch per-page Marker progress in the log pane and progress bar

### Optional settings
- **Page Range** — e.g. `37-84` for Session 1 only
- **Save raw Marker output** — Saves `.raw.md` for later post-process-only runs

### Automatic Updates

The app checks for pipeline updates every 30 seconds in the background. When a new version is available, a green banner appears at the top of the window. Click **Update Now** to download the latest `run.py` and template configs — takes 2 seconds, no reinstall needed. Fails silently if offline.

## Building the Installer

### Cloud Build (recommended)

Go to [Actions → Build Installers](../../actions/workflows/build-installers.yml) → Run workflow. The Windows `.exe` installer is uploaded as an artifact. No local toolchain needed.

### Local Build (alternative)

Open a **Command Prompt** (not Git Bash):

```
cd C:\Users\Steve\Affinity-to-Markdown\windows-installer
build.bat
```

Requires Python 3.11 venv with deps installed. Optionally installs [Inno Setup 6](https://jrsoftware.org/isinfo.php) for the `.exe` wrapper.

## Architecture

```
windows-installer/
  main.py                          # Entry point
  gui.py                           # tkinter GUI with update banner
  pipeline.py                      # Wraps run.py, captures tqdm progress
  config.py                        # OTA-aware path resolution
  updater.py                       # Checks GitHub for pipeline updates
  affinity_converter_win.spec      # PyInstaller build spec
  installer.iss                    # Inno Setup installer config
  build.bat                        # Local build script
  requirements.txt                 # Python dependencies
```

### Key design

- `run.py` is **imported, not copied** — no code duplication with the pipeline
- GUI **never blocks** — pipeline runs in a background thread with a message queue
- **Real Marker progress** — captures tqdm output from stderr, shows per-page progress with ETA
- **OTA updates** — checks `update-manifest.json` on GitHub every 30s, downloads to `~/.affinity-converter/updates/`

## Environment Variables

| Variable | Purpose |
|----------|--------|
| `GOOGLE_API_KEY` | Optional — enables Gemini LLM during Marker conversion |
