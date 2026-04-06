# Affinity-PDF-Markdown Converter

Converts designed book PDFs (from Affinity Publisher) into clean, structured Markdown with semantic headings, blockquotes, citations, callouts, and tagged user-input areas.

Built by [Noble Collective](https://github.com/Noble-Collective).

## Project Structure

```
Affinity-to-Markdown/
├── marker-pdf/              ← Core conversion pipeline
│   ├── run.py               # All pipeline logic (~1,660 lines)
│   ├── templates/homestead/ # Book-specific config + question tags
│   ├── testing/             # Raw/processed output files, debug scripts
│   └── README.md            # Pipeline architecture & usage docs
│
├── windows-installer/       ← Windows desktop app + build scripts
│   ├── main.py, gui.py, pipeline.py, config.py
│   ├── build.bat            # Automated build (PyInstaller + Inno Setup)
│   └── README.md            # Windows build & packaging docs
│
├── mac-installer/           ← macOS desktop app + build scripts
│   ├── main.py, gui.py, pipeline.py, config.py
│   ├── build.sh             # Automated build (.app + .dmg)
│   └── README.md            # macOS build & packaging docs
│
├── archive/                 ← Retired code from earlier project phases
│   ├── afpub-converter/     # Binary .afpub parser (Phase 1, abandoned)
│   └── web-app/             # Cloud Run web app (Phase 2, superseded)
│
└── .github/workflows/       ← CI/CD (Cloud Run deploy, manual trigger)
```

## How It Works

The pipeline has two layers:

1. **Marker** (ML-based) — Extracts text from PDF using surya layout detection. Produces raw Markdown (~80% correct).
2. **PyMuPDF** (font-driven) — 30+ post-processing passes that correct Marker's mistakes using font properties (weight, size ratios, position). Produces clean, structured output.

All book-specific configuration lives in `marker-pdf/templates/<book>/pdf_config.yaml`. The pipeline code (`run.py`) is generic across books.

## Quick Start

### Run from CLI (development)

```bash
cd marker-pdf
source venv311/Scripts/activate   # Windows Git Bash

# Full conversion (~10-15 min on CPU)
python run.py book.pdf --save-raw --template homestead

# Post-process only (~2 seconds)
python run.py raw.md book.pdf --postprocess --template homestead

# Font calibration for a new book
python run.py newbook.pdf --dump-fonts
```

### Run from Desktop App

```bash
cd windows-installer    # or mac-installer
python main.py
```

See the README in each installer directory for build & packaging instructions.

## Adding a New Book Template

1. Run `python run.py newbook.pdf --dump-fonts` to see the font table
2. Create `marker-pdf/templates/newbook/pdf_config.yaml` with heading ratios matched to the font table
3. Run `python run.py newbook.pdf --template newbook --save-raw`
4. Iterate on `pdf_config.yaml` until output is clean
5. Optionally add `questions_final.yaml` for question tagging

See `marker-pdf/README.md` for full template system docs.

## Building Distributable Installers

### Windows

```
cd windows-installer
build.bat
```

Produces `Output\Affinity-PDF-Markdown-Converter_Setup.exe` (requires [Inno Setup 6](https://jrsoftware.org/isinfo.php) for the installer step; without it, produces a distributable folder).

### macOS

```bash
cd mac-installer
chmod +x build.sh
./build.sh
```

Produces `dist/Affinity-PDF-Markdown-Converter-0.1.0.dmg`.

## Dependencies

- Python 3.11
- marker-pdf 1.10.2 (pinned)
- PyMuPDF, PyYAML
- PyTorch (CPU, ~1.5GB)
- Surya ML models (~500MB, auto-download on first run)

Total disk: ~2–3GB installed.
