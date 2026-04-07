# -*- mode: python ; coding: utf-8 -*-
"""
affinity_converter_win.spec — PyInstaller build spec for Windows.

Uses collect_submodules/collect_data_files to grab ALL dependencies
from marker, surya, and pdftext rather than hand-picking imports.
This makes the installer ~50MB larger but eliminates runtime
ModuleNotFoundError and missing data file errors.
"""

import os
import importlib.util
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

SPEC_DIR = Path(os.path.abspath(SPECPATH))
REPO_ROOT = SPEC_DIR.parent
MARKER_PDF = REPO_ROOT / "marker-pdf"

# Find installed marker package for font location
_ms = importlib.util.find_spec("marker")
MARKER_PKG = os.path.dirname(_ms.origin) if _ms else ""
MARKER_PARENT = os.path.dirname(MARKER_PKG) if MARKER_PKG else ""

# ── Collect ALL submodules (catches dynamic/registry imports) ────────
_hidden = (
    collect_submodules("marker") +
    collect_submodules("surya") +
    collect_submodules("pdftext") +
    collect_submodules("google.genai") +
    collect_submodules("google.auth") +
    collect_submodules("google.api_core") +
    [
        "yaml", "fitz", "torch",
        "PIL", "PIL.Image",
        "regex", "certifi", "charset_normalizer",
        "huggingface_hub", "safetensors",
        "pypdfium2", "pypdfium2._helpers",
    ]
)

# ── Collect ALL data files (fonts, configs, language data) ───────────
_datas = (
    collect_data_files("marker") +
    collect_data_files("surya") +
    collect_data_files("pdftext") +
    collect_data_files("pypdfium2") +
    collect_data_files("certifi") +
    [
        (str(MARKER_PDF / "run.py"), "marker-pdf"),
        (str(MARKER_PDF / "model_cache.py"), "marker-pdf"),
        (str(MARKER_PDF / "model_loader.py"), "marker-pdf"),
        (str(MARKER_PDF / "download_models.py"), "marker-pdf"),
        (str(MARKER_PDF / "templates"), "marker-pdf/templates"),
    ]
)
# Pre-downloaded Marker fonts (created by workflow step)
_static = os.path.join(MARKER_PARENT, "static")
if os.path.isdir(_static):
    _datas.append((_static, "static"))

a = Analysis(
    ["main.py"],
    pathex=[str(SPEC_DIR), str(MARKER_PDF)],
    binaries=[],
    datas=_datas,
    hiddenimports=_hidden,
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=["fastapi", "uvicorn", "google.cloud.storage"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Affinity-PDF-Markdown Converter",
    debug=False, bootloader_ignore_signals=False,
    strip=False, upx=True, console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=True, upx_exclude=[],
    name="Affinity-PDF-Markdown Converter",
)
