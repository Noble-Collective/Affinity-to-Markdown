"""
config.py — App paths, platform detection, settings.
"""

import os
import sys
import platform
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)

if FROZEN:
    APP_DIR = Path(sys._MEIPASS)
    _BUNDLED_MARKER_PDF = APP_DIR / "marker-pdf"
else:
    APP_DIR = Path(__file__).resolve().parent
    _BUNDLED_MARKER_PDF = APP_DIR.parent / "marker-pdf"

UPDATES_DIR = Path.home() / ".affinity-converter" / "updates"

def _effective_marker_pdf() -> Path:
    updated = UPDATES_DIR / "marker-pdf" / "run.py"
    if updated.exists():
        return UPDATES_DIR / "marker-pdf"
    return _BUNDLED_MARKER_PDF

MARKER_PDF_DIR = _effective_marker_pdf()
TEMPLATES_DIR = _BUNDLED_MARKER_PDF / "templates"
RUN_PY = MARKER_PDF_DIR / "run.py"
MODEL_CACHE_DIR = Path.home() / ".cache" / "datalab" / "models"

IS_WINDOWS = platform.system() == "Windows"
IS_MACOS = platform.system() == "Darwin"

APP_NAME = "Affinity-PDF-Markdown Converter"
APP_VERSION = "0.1.0"


def get_google_api_key() -> str:
    try:
        from _build_secrets import GOOGLE_API_KEY
        if GOOGLE_API_KEY:
            return GOOGLE_API_KEY
    except ImportError:
        pass
    return os.environ.get("GOOGLE_API_KEY", "")


def patch_marker_font_path():
    """Override settings.STATIC_DIR to a writable location.

    Marker reads settings.STATIC_DIR (computed at import time from __file__)
    to decide where to store/find fonts. In frozen apps this points to
    read-only Program Files or .app bundle. Just override the setting.
    """
    if not FROZEN:
        return
    writable = os.path.join(os.path.expanduser("~"), ".affinity-converter", "static")
    os.makedirs(writable, exist_ok=True)
    try:
        from marker.settings import settings
        settings.STATIC_DIR = writable
    except Exception:
        pass


def get_available_templates() -> list[str]:
    templates = set()
    for base in [UPDATES_DIR / "marker-pdf" / "templates", _BUNDLED_MARKER_PDF / "templates"]:
        if base.is_dir():
            for d in base.iterdir():
                if d.is_dir() and (d / "pdf_config.yaml").exists():
                    templates.add(d.name)
    return sorted(templates)

def get_template_dir(template_name: str) -> Path:
    updated = UPDATES_DIR / "marker-pdf" / "templates" / template_name
    if updated.exists() and (updated / "pdf_config.yaml").exists():
        return updated
    return _BUNDLED_MARKER_PDF / "templates" / template_name

def check_models_downloaded() -> bool:
    if not MODEL_CACHE_DIR.exists(): return False
    return len([d for d in MODEL_CACHE_DIR.iterdir() if d.is_dir()]) >= 1

def check_marker_pdf_dir() -> bool:
    return RUN_PY.exists()
