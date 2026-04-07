# -*- mode: python ; coding: utf-8 -*-
"""
affinity_converter_mac.spec — PyInstaller build spec for macOS.
"""

import os
import importlib.util
from pathlib import Path

SPEC_DIR = Path(os.path.abspath(SPECPATH))
REPO_ROOT = SPEC_DIR.parent
MARKER_PDF = REPO_ROOT / "marker-pdf"

_ms = importlib.util.find_spec("marker")
MARKER_PKG = os.path.dirname(_ms.origin) if _ms else ""

_datas = [
    (str(MARKER_PDF / "run.py"), "marker-pdf"),
    (str(MARKER_PDF / "model_cache.py"), "marker-pdf"),
    (str(MARKER_PDF / "model_loader.py"), "marker-pdf"),
    (str(MARKER_PDF / "download_models.py"), "marker-pdf"),
    (str(MARKER_PDF / "templates"), "marker-pdf/templates"),
]
if MARKER_PKG and os.path.isdir(os.path.join(MARKER_PKG, "static")):
    _datas.append((os.path.join(MARKER_PKG, "static"), "marker/static"))

a = Analysis(
    ["main.py"],
    pathex=[str(SPEC_DIR), str(MARKER_PDF)],
    binaries=[],
    datas=_datas,
    hiddenimports=[
        "yaml", "fitz", "torch", "marker", "marker.models",
        "marker.converters.pdf", "marker.processors.block_relabel",
        "marker.schema.registry",
        "_tkinter", "tkinter", "tkinter.ttk",
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
