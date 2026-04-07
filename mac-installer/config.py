"""
config.py — App paths, platform detection, settings.
Supports OTA updates: checks ~/.affinity-converter/updates/ first.
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
    """Return Google API key: build-time embedded secret first, env var fallback."""
    try:
        from _build_secrets import GOOGLE_API_KEY
        if GOOGLE_API_KEY:
            return GOOGLE_API_KEY
    except ImportError:
        pass
    return os.environ.get("GOOGLE_API_KEY", "")


def patch_marker_font_path():
    """Monkey-patch Marker's download_font for read-only install dirs.

    Problem: Marker's download_font() creates a 'static/' dir relative
    to its __file__ to store a font. In frozen apps this is read-only.

    Fix: Replace download_font in ALL modules that imported it (not just
    marker.util) with a version that redirects to ~/.affinity-converter/.
    Must scan sys.modules because 'from marker.util import download_font'
    creates local references that a simple module-level patch won't reach.
    """
    if not FROZEN:
        return
    try:
        import marker.util
        _orig = marker.util.download_font
        if getattr(_orig, '_patched', False):
            return

        _WRITABLE_STATIC = os.path.join(
            os.path.expanduser("~"), ".affinity-converter", "static"
        )

        def _safe_download_font(*a, **kw):
            # Always redirect __file__ to writable location BEFORE calling
            os.makedirs(_WRITABLE_STATIC, exist_ok=True)
            old_file = marker.util.__file__
            writable_base = os.path.join(
                os.path.expanduser("~"), ".affinity-converter"
            )
            marker.util.__file__ = os.path.join(
                writable_base, "marker", "util.py"
            )
            try:
                return _orig(*a, **kw)
            except (PermissionError, OSError):
                # If __file__ redirect didn't help (precomputed path),
                # create font dir ourselves and retry
                os.makedirs(_WRITABLE_STATIC, exist_ok=True)
                return _orig(*a, **kw)
            finally:
                marker.util.__file__ = old_file

        _safe_download_font._patched = True

        # Replace in marker.util
        marker.util.download_font = _safe_download_font

        # Replace in ALL loaded modules that imported download_font
        # (catches 'from marker.util import download_font' local refs)
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
