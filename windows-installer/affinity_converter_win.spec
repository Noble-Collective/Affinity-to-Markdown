# -*- mode: python ; coding: utf-8 -*-
"""
affinity_converter_win.spec — PyInstaller build spec for Windows.
"""

import os
import importlib.util
from pathlib import Path

SPEC_DIR = Path(os.path.abspath(SPECPATH))
REPO_ROOT = SPEC_DIR.parent
MARKER_PDF = REPO_ROOT / "marker-pdf"

# Find installed marker package to include its static fonts
_ms = importlib.util.find_spec("marker")
MARKER_PKG = os.path.dirname(_ms.origin) if _ms else ""
# Marker creates static/ one level ABOVE the marker package dir
MARKER_PARENT = os.path.dirname(MARKER_PKG) if MARKER_PKG else ""

_datas = [
    (str(MARKER_PDF / "run.py"), "marker-pdf"),
    (str(MARKER_PDF / "model_cache.py"), "marker-pdf"),
    (str(MARKER_PDF / "model_loader.py"), "marker-pdf"),
    (str(MARKER_PDF / "download_models.py"), "marker-pdf"),
    (str(MARKER_PDF / "templates"), "marker-pdf/templates"),
]
# Include pre-downloaded Marker fonts at bundle root (where Marker looks for them)
_static = os.path.join(MARKER_PARENT, "static")
if os.path.isdir(_static):
    _datas.append((_static, "static"))

a = Analysis(
    ["main.py"],
    pathex=[str(SPEC_DIR), str(MARKER_PDF)],
    binaries=[],
    datas=_datas,
    hiddenimports=[
        "yaml", "fitz", "torch", "marker", "marker.models",
        "marker.converters.pdf", "marker.processors.block_relabel",
        "marker.schema.registry",
        "google.auth", "google.auth.transport.requests", "google.genai",
    ],
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
