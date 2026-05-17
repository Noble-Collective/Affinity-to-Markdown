# Affinity-PDF-Markdown Converter

Converts designed book PDFs (from Affinity Publisher) into clean, structured Markdown with semantic headings, blockquotes, citations, callouts, and tagged user-input areas.

Built by [Noble Collective](https://github.com/Noble-Collective).

## Project Structure

```
Affinity-to-Markdown/
├── marker-pdf/              ← Core conversion pipeline
│   ├── run.py               # All pipeline logic
│   ├── templates/           # Series/book configs + question tags
│   │   ├── passage/                  ← Passage series (Times New Roman)
│   │   │   ├── series_config.yaml    # Shared font rules
│   │   │   └── homestead/
│   │   │       ├── book_config.yaml  # Book-specific overrides
│   │   │       └── questions_final.yaml
│   │   ├── classics/                 ← A Library of Classics (EB Garamond)
│   │   │   ├── series_config.yaml
│   │   │   └── oration/
│   │   │       ├── book_config.yaml
│   │   │       └── questions_final.yaml
│   │   └── appelle_du_christ/        ← Flat template (no series)
│   │       └── pdf_config.yaml
│   ├── testing/             # Raw/processed output files, debug scripts
│   └── README.md            # Pipeline architecture & usage docs
│
├── windows-installer/       ← Windows desktop app
├── mac-installer/           ← macOS desktop app (signed + notarized)
├── update-manifest.json     ← OTA update version (bump to push updates)
├── archive/                 ← Retired code from earlier phases
└── .github/workflows/       ← Cloud builds + CI/CD
```

## How It Works

The pipeline has two layers:

1. **Marker** (ML-based) — Extracts text from PDF using surya layout detection. Produces raw Markdown (~80% correct).
2. **PyMuPDF** (font-driven) — 30+ post-processing passes that correct Marker's mistakes using font properties (weight, size ratios, position). Produces clean, structured output.

Book-specific configuration lives in template files under `marker-pdf/templates/`. Templates are organized in two ways:

- **Series/book** (preferred): `templates/<series>/series_config.yaml` holds shared font rules; `templates/<series>/<book>/book_config.yaml` holds book-specific overrides. The pipeline merges both at runtime.
- **Flat** (legacy): `templates/<template>/pdf_config.yaml` as a single file.

The pipeline code (`run.py`) is generic across books.

## Building Installers (Cloud — Recommended)

Both Windows and Mac installers are built in the cloud via GitHub Actions. No local setup needed.

1. Go to **[Actions → Build Installers](../../actions/workflows/build-installers.yml)**
2. Click **Run workflow** → **Run workflow**
3. Wait ~15 minutes (both platforms build in parallel)
4. Download **Windows-Installer** (`.exe`) and **macOS-Installer** (`.dmg`) from the Artifacts section

The Mac build is automatically code-signed with a Developer ID certificate and notarized by Apple — installs cleanly with zero Gatekeeper warnings.

The Windows build produces a standard installer (Next → Next → Install) that puts the app in Program Files with Start Menu shortcuts.

## OTA Updates

Installed apps check for pipeline updates every 30 seconds in the background. When you push changes to `run.py` or template configs:

1. Push your changes to GitHub
2. Edit `update-manifest.json`: bump `version`, update `notes`
3. Push
4. Team members see a green banner in the app within 30 seconds
5. They click **Update Now** — downloads in 2 seconds, no reinstall needed

Only small files (run.py, configs) are downloaded — the heavy dependencies (Python, torch, Marker) stay as-is. A full reinstall is only needed if torch or Marker versions change (rare).

## Running from CLI (Development)

```bash
cd marker-pdf
source venv311/Scripts/activate   # Windows Git Bash

# Full conversion — series/book template (~10-15 min on CPU)
python run.py book.pdf --save-raw --template passage --book homestead

# Full conversion — flat template
python run.py book.pdf --save-raw --template appelle_du_christ

# Post-process only (~2 seconds)
python run.py raw.md book.pdf --postprocess --template passage --book homestead

# Font calibration for a new book
python run.py newbook.pdf --dump-fonts
```

The default template is `passage`. When using a series template, `--book` selects the book within that series.

## Adding a New Book Template

**Adding a book to an existing series:**

1. Run `python run.py newbook.pdf --dump-fonts` to see the font table
2. Create `marker-pdf/templates/<series>/newbook/book_config.yaml` with book-specific overrides (heading ratios, hierarchy, etc.). Shared font rules are inherited from `series_config.yaml`.
3. Run `python run.py newbook.pdf --template <series> --book newbook --save-raw`
4. Iterate on `book_config.yaml` until output is clean
5. Optionally add `questions_final.yaml` for question tagging
6. Bump `update-manifest.json` to push the new template to all installed apps

**Adding a new series:**

1. Create `marker-pdf/templates/newseries/series_config.yaml` with shared font rules
2. Create a book directory under it (see above)

**Adding a standalone (flat) template:**

1. Create `marker-pdf/templates/newtemplate/pdf_config.yaml` with all config in one file
2. Run with `--template newtemplate` (no `--book` flag)

See `marker-pdf/README.md` for full template system docs.

## Dependencies

All bundled into the installers — end users install nothing.

- Python 3.11
- marker-pdf 1.10.2 (pinned)
- PyMuPDF, PyYAML
- PyTorch (CPU, ~1.5GB)
- Surya ML models (~500MB, auto-download on first run)

Total disk: ~2–3GB installed.
