# -*- mode: python ; coding: utf-8 -*-
"""
homestead_converter.spec — PyInstaller build spec for Windows.

Build with:
    cd windows-installer
    pyinstaller homestead_converter.spec

Output: dist/HomeStead Converter/  (folder distribution)
"""

import os
from pathlib import Path

# Paths relative to this spec file
SPEC_DIR = Path(os.path.abspath(SPECPATH))
REPO_ROOT = SPEC_DIR.parent
MARKER_PDF = REPO_ROOT / "marker-pdf"

a = Analysis(
    ["main.py"],
    pathex=[str(SPEC_DIR), str(MARKER_PDF)],
    binaries=[],
    datas=[
        # Bundle marker-pdf/run.py and supporting modules
        (str(MARKER_PDF / "run.py"), "marker-pdf"),
        (str(MARKER_PDF / "model_cache.py"), "marker-pdf"),
        (str(MARKER_PDF / "model_loader.py"), "marker-pdf"),
        (str(MARKER_PDF / "download_models.py"), "marker-pdf"),
        # Bundle templates
        (str(MARKER_PDF / "templates"), "marker-pdf/templates"),
    ],
    hiddenimports=[
        "yaml",
        "fitz",
        "torch",
        "marker",
        "marker.models",
        "marker.converters.pdf",
        "marker.processors.block_relabel",
        "marker.schema.registry",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude Cloud Run / web server deps (not needed in desktop)
        "fastapi",
        "uvicorn",
        "google.cloud.storage",
        "google.auth",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="HomeStead Converter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # No console window (GUI app)
    disable_windowed_traceback=False,
    # icon="assets/icon.ico",  # Uncomment when icon is available
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="HomeStead Converter",
)
