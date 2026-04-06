# Affinity-PDF-Markdown Converter — Windows

Windows desktop app for the PDF-to-Markdown conversion pipeline.

## Quick Start (Development)

```bash
cd windows-installer
source ../marker-pdf/venv311/Scripts/activate   # Git Bash
python main.py
```

## Using the App

1. **Select a PDF** — Browse to the book PDF
2. **Choose a template** — Defaults to `homestead`
3. **Pick output path** — Auto-filled based on PDF name
4. **Choose mode:**
   - **Full Conversion** — Marker ML + post-processing (~10-15 min on CPU)
   - **Post-process Only** — From existing `.raw.md` (~2 seconds)
5. **Click Convert** — Watch progress in the log pane and progress bar

### Optional settings
- **Page Range** — e.g. `37-84` for Session 1 only
- **Save raw Marker output** — Saves `.raw.md` for later post-process-only runs

## Building the Installer

### Step 1: PyInstaller

Open a **Command Prompt** (not Git Bash):

```
cd C:\Users\Steve\Affinity-to-Markdown\windows-installer
build.bat
```

Produces `dist\Affinity-PDF-Markdown Converter\`.

### Step 2: Inno Setup (optional)

1. Install [Inno Setup 6](https://jrsoftware.org/isinfo.php)
2. Re-run `build.bat` — auto-detects Inno Setup
3. Output: `Output\Affinity-PDF-Markdown-Converter_Setup.exe`

## Architecture

```
windows-installer/
  main.py                          # Entry point
  gui.py                           # tkinter GUI
  pipeline.py                      # Wraps run.py in background thread
  config.py                        # Paths, platform detection
  affinity_converter_win.spec      # PyInstaller build spec
  installer.iss                    # Inno Setup installer config
  build.bat                        # Automated build script
  requirements.txt                 # Python dependencies
```

### Key design

- `run.py` is **imported, not copied** — no code duplication
- GUI **never blocks** — pipeline runs in a background thread
- **stdout capture** — `print()` from `run.py` goes to the GUI log pane
- **Progress ticker** — during Marker extraction, shows elapsed time every 3s

## Environment Variables

| Variable | Purpose |
|----------|--------|
| `GOOGLE_API_KEY` | Optional — enables Gemini LLM during Marker conversion |
