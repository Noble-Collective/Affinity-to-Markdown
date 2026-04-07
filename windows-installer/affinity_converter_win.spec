# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

SPEC_DIR = Path(os.path.abspath(SPECPATH))
REPO_ROOT = SPEC_DIR.parent
MARKER_PDF = REPO_ROOT / "marker-pdf"

# Read STATIC_DIR directly from Marker settings — the exact path download_font uses
_static = ""
try:
    from marker.settings import settings
    _static = settings.STATIC_DIR
    print(f"[SPEC] STATIC_DIR = {_static}, exists = {os.path.isdir(_static)}")
    if os.path.isdir(_static):
        print(f"[SPEC] Contents: {os.listdir(_static)}")
except Exception as e:
    print(f"[SPEC] Could not read marker.settings: {e}")

_hidden = (
    collect_submodules("marker") +
    collect_submodules("surya") +
    collect_submodules("pdftext") +
    collect_submodules("google.genai") +
    collect_submodules("google.auth") +
    collect_submodules("google.api_core") +
    ["yaml", "fitz", "torch", "PIL", "PIL.Image", "regex", "certifi",
     "charset_normalizer", "huggingface_hub", "safetensors",
     "pypdfium2", "pypdfium2._helpers"]
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
if _static and os.path.isdir(_static):
    _datas.append((_static, "static"))
    print(f"[SPEC] Bundling font dir as 'static/'")

a = Analysis(
    ["main.py"],
    pathex=[str(SPEC_DIR), str(MARKER_PDF)],
    binaries=[], datas=_datas, hiddenimports=_hidden,
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=["fastapi", "uvicorn", "google.cloud.storage"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True,
    name="Affinity-PDF-Markdown Converter",
    debug=False, bootloader_ignore_signals=False,
    strip=False, upx=True, console=False,
    disable_windowed_traceback=False)
coll = COLLECT(exe, a.binaries, a.datas,
    strip=False, upx=True, upx_exclude=[],
    name="Affinity-PDF-Markdown Converter")
