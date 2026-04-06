"""
config.py — App paths, platform detection, settings.

Resolves paths relative to the repo root so that both development
(running from source) and PyInstaller-frozen builds work correctly.
"""

import sys
import platform
from pathlib import Path


FROZEN = getattr(sys, "frozen", False)

if FROZEN:
    APP_DIR = Path(sys.executable).parent
    MARKER_PDF_DIR = APP_DIR / "marker-pdf"
else:
    APP_DIR = Path(__file__).resolve().parent
    MARKER_PDF_DIR = APP_DIR.parent / "marker-pdf"


TEMPLATES_DIR = MARKER_PDF_DIR / "templates"
RUN_PY = MARKER_PDF_DIR / "run.py"
MODEL_CACHE_DIR = Path.home() / ".cache" / "datalab" / "models"

IS_WINDOWS = platform.system() == "Windows"
IS_MACOS = platform.system() == "Darwin"

APP_NAME = "Affinity-PDF-Markdown Converter"
APP_VERSION = "0.1.0"


def get_available_templates() -> list[str]:
    if not TEMPLATES_DIR.is_dir():
        return []
    return sorted(
        d.name for d in TEMPLATES_DIR.iterdir()
        if d.is_dir() and (d / "pdf_config.yaml").exists()
    )

def check_models_downloaded() -> bool:
    if not MODEL_CACHE_DIR.exists():
        return False
    return len([d for d in MODEL_CACHE_DIR.iterdir() if d.is_dir()]) >= 1

def check_marker_pdf_dir() -> bool:
    return RUN_PY.exists()
