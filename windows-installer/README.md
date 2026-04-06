# HomeStead Converter — Desktop App

Cross-platform desktop GUI for the PDF-to-Markdown conversion pipeline.

## Quick Start (Development)

```bash
# From the repo root (Affinity-to-Markdown/)
cd windows-installer

# Create a Python 3.11 venv (or reuse marker-pdf/venv311)
python -m venv venv311
venv311\Scripts\activate          # Windows Git Bash
# source venv311/bin/activate     # macOS/Linux

pip install -r requirements.txt

# Run the app
python main.py
```

**First-run note:** The ML models (~500MB) will download automatically the first time you run a full conversion. This is a one-time download — subsequent runs use the cached models from `~/.cache/datalab/models/`.

## Using the App

1. **Select a PDF** — Browse to the book PDF
2. **Choose a template** — Defaults to `homestead`
3. **Pick output path** — Auto-filled based on PDF name
4. **Choose mode:**
   - **Full Conversion** — Runs Marker ML extraction + post-processing (~10-15 min on CPU)
   - **Post-process Only** — Skips Marker, uses an existing `.raw.md` file (~2 seconds)
5. **Click Convert**

### Optional settings
- **Page Range** — Convert only specific pages (e.g. `37-84` for Session 1)
- **Save raw Marker output** — Saves the `.raw.md` file for later post-process-only runs

## Architecture

```
windows-installer/
  main.py              # Entry point — launches tkinter GUI
  gui.py               # UI: file pickers, progress bar, log pane
  pipeline.py          # Wraps run.py functions for background execution
  config.py            # Paths, platform detection, settings
  requirements.txt     # Python dependencies
  homestead_converter.spec  # PyInstaller build spec (Windows)
  README.md            # This file
```

### How it works

```
┌─────────────────────────────────────────────────┐
│                 GUI (main thread)                │
│                                                   │
│  File pickers → template → mode → [Convert]      │
│                                                   │
│  Progress bar ◄── polls queue every 50ms         │
│  Log pane     ◄──┘                               │
└────────────────────┬────────────────────────────┘
                     │ starts background thread
                     ▼
┌─────────────────────────────────────────────────┐
│           PipelineRunner (worker thread)          │
│                                                   │
│  Imports run.py from marker-pdf/                 │
│  Captures stdout → queue → GUI log               │
│  Reports progress → queue → GUI progress bar     │
│  Calls run.py functions directly:                │
│    detect_body_font()                            │
│    build_heading_map(), build_skip_set(), etc.   │
│    PdfConverter() (Marker ML)                    │
│    post_process() (30+ passes)                   │
│                                                   │
│  On completion → queue → GUI "Done" state        │
└─────────────────────────────────────────────────┘
```

**Key design decisions:**
- `run.py` is **imported, not copied** — the desktop app adds `marker-pdf/` to `sys.path` and calls its functions directly. No code duplication.
- The GUI **never blocks** — the pipeline runs in a daemon thread; the GUI polls a message queue to pick up log lines, progress updates, and completion signals.
- **stdout capture** — `print()` calls inside `run.py` are intercepted by a custom file-like object and forwarded to the GUI log pane.

## Building a Distributable (Windows)

```bash
cd windows-installer
venv311\Scripts\activate
pyinstaller homestead_converter.spec
```

This produces `dist/HomeStead Converter/` — a folder containing the `.exe` and all dependencies. The folder can be distributed as-is or wrapped in an Inno Setup installer.

**Size note:** The full build (with torch + surya models) is ~2-3GB. The ML models download on first run, so the build itself is closer to ~2GB (torch + marker + pymupdf + Python runtime).

### macOS

The `.spec` file is Windows-oriented. For macOS:
1. Change `console=False` to the appropriate macOS settings
2. Use `.icns` icon format
3. Build produces a `.app` bundle
4. Consider separate builds for Intel and Apple Silicon (torch wheels differ)

## Reusing marker-pdf's venv

If you already have `marker-pdf/venv311` set up, you can reuse it:

```bash
cd windows-installer
..\marker-pdf\venv311\Scripts\activate   # Windows
python main.py
```

No separate install needed — the desktop app only imports standard library (`tkinter`) on top of the existing marker-pdf dependencies.

## Environment Variables

| Variable | Purpose |
|----------|--------|
| `GOOGLE_API_KEY` | Optional — enables Gemini LLM integration during Marker conversion |
