# -*- mode: python ; coding: utf-8 -*-
"""
affinity_converter_mac.spec — PyInstaller build spec for macOS.

Uses collect_submodules/collect_data_files to grab ALL dependencies
from marker, surya, and pdftext rather than hand-picking imports.
"""

import os
import importlib.util
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

SPEC_DIR = Path(os.path.abspath(SPECPATH))
REPO_ROOT = SPEC_DIR.parent
MARKER_PDF = REPO_ROOT / "marker-pdf"

_ms = importlib.util.find_spec("marker")
MARKER_PKG = os.path.dirname(_ms.origin) if _ms else ""
MARKER_PARENT = os.path.dirname(MARKER_PKG) if MARKER_PKG else ""

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
        "_tkinter", "tkinter", "tkinter.ttk",
    ]
)

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
    strip=False, upx=False, console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False,
    name="Affinity-PDF-Markdown Converter",
)

app = BUNDLE(
    coll,
    name="Affinity-PDF-Markdown Converter.app",
    bundle_identifier="com.noblecollective.affinity-converter",
    info_plist={
        "CFBundleName": "Affinity-PDF-Markdown Converter",
        "CFBundleDisplayName": "Affinity-PDF-Markdown Converter",
        "CFBundleVersion": "0.1.0",
        "CFBundleShortVersionString": "0.1.0",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "10.15",
    },
)
