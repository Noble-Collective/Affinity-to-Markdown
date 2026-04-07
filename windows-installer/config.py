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
    """Replace download_font in ALL modules with a version that uses a writable dir.

    Must scan sys.modules because 'from marker.util import download_font'
    creates local references that a simple marker.util.download_font = X misses.
    """
    if not FROZEN:
        return
    try:
        import marker.util
        _orig = marker.util.download_font
        if getattr(_orig, '_patched', False):
            return

        _WRITABLE = os.path.join(os.path.expanduser("~"), ".affinity-converter")

        def _safe_download_font(*a, **kw):
            os.makedirs(os.path.join(_WRITABLE, "static"), exist_ok=True)
            old_file = marker.util.__file__
            marker.util.__file__ = os.path.join(_WRITABLE, "marker", "util.py")
            os.makedirs(os.path.join(_WRITABLE, "marker"), exist_ok=True)
            try:
                return _orig(*a, **kw)
            except (PermissionError, OSError):
                return _orig(*a, **kw)
            finally:
                marker.util.__file__ = old_file

        _safe_download_font._patched = True
        marker.util.download_font = _safe_download_font

        for name, mod in list(sys.modules.items()):
            if mod is None:
                continue
            try:
                if hasattr(mod, 'download_font') and getattr(mod, 'download_font') is _orig:
                    setattr(mod, 'download_font', _safe_download_font)
            except Exception:
                continue
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
