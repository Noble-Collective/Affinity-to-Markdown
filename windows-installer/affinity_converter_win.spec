# -*- mode: python ; coding: utf-8 -*-
"""
affinity_converter_win.spec — PyInstaller build spec for Windows.

Build with:
    cd windows-installer
    pyinstaller affinity_converter_win.spec

Output: dist/Affinity-PDF-Markdown Converter/  (folder distribution)
"""

import os
from pathlib import Path

SPEC_DIR = Path(os.path.abspath(SPECPATH))
REPO_ROOT = SPEC_DIR.parent
MARKER_PDF = REPO_ROOT / "marker-pdf"

a = Analysis(
    ["main.py"],
    pathex=[str(SPEC_DIR), str(MARKER_PDF)],
    binaries=[],
    datas=[
        (str(MARKER_PDF / "run.py"), "marker-pdf"),
        (str(MARKER_PDF / "model_cache.py"), "marker-pdf"),
        (str(MARKER_PDF / "model_loader.py"), "marker-pdf"),
        (str(MARKER_PDF / "download_models.py"), "marker-pdf"),
        (str(MARKER_PDF / "templates"), "marker-pdf/templates"),
    ],
    hiddenimports=[
        "yaml", "fitz", "torch", "marker", "marker.models",
        "marker.converters.pdf", "marker.processors.block_relabel",
        "marker.schema.registry",
    ],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=["fastapi", "uvicorn", "google.cloud.storage", "google.auth"],
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
    # icon="assets/icon.ico",
)

coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=True, upx_exclude=[],
    name="Affinity-PDF-Markdown Converter",
)
