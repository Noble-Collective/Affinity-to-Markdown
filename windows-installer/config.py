"""
config.py — App paths, platform detection, settings.

Resolves paths relative to the repo root so that both development
(running from source) and PyInstaller-frozen builds work correctly.
"""

import sys
import platform
from pathlib import Path


# ── Frozen vs. development mode ──────────────────────────────────────────────

FROZEN = getattr(sys, "frozen", False)

if FROZEN:
    # PyInstaller sets sys._MEIPASS to the temp extraction dir (one-dir mode)
    # or bundles everything alongside the exe.
    APP_DIR = Path(sys.executable).parent
    MARKER_PDF_DIR = APP_DIR / "marker-pdf"
else:
    # Development: windows-installer/ is sibling to marker-pdf/ in the repo
    APP_DIR = Path(__file__).resolve().parent
    MARKER_PDF_DIR = APP_DIR.parent / "marker-pdf"


# ── Key paths ────────────────────────────────────────────────────────

TEMPLATES_DIR = MARKER_PDF_DIR / "templates"
RUN_PY = MARKER_PDF_DIR / "run.py"

# Model cache (surya downloads models here on first run)
MODEL_CACHE_DIR = Path.home() / ".cache" / "datalab" / "models"


# ── Platform ─────────────────────────────────────────────────────────

IS_WINDOWS = platform.system() == "Windows"
IS_MACOS = platform.system() == "Darwin"


# ── App metadata ─────────────────────────────────────────────────────

APP_NAME = "HomeStead Converter"
APP_VERSION = "0.1.0"


def get_available_templates() -> list[str]:
    """Return a list of template names (subdirectory names under templates/)."""
    if not TEMPLATES_DIR.is_dir():
        return []
    return sorted(
        d.name
        for d in TEMPLATES_DIR.iterdir()
        if d.is_dir() and (d / "pdf_config.yaml").exists()
    )


def check_models_downloaded() -> bool:
    """Check whether surya ML models appear to be cached locally."""
    if not MODEL_CACHE_DIR.exists():
        return False
    # Surya downloads several model folders; check for at least one
    subdirs = [d for d in MODEL_CACHE_DIR.iterdir() if d.is_dir()]
    return len(subdirs) >= 1


def check_marker_pdf_dir() -> bool:
    """Verify the marker-pdf directory and run.py are accessible."""
    return RUN_PY.exists()
