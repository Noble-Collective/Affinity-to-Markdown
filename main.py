import base64
import datetime
import io
import json
import os
import sys
import tempfile
import uuid
from contextlib import redirect_stdout
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles


def _base_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


BASE_DIR = _base_dir()
TEMPLATES_DIR = BASE_DIR / 'templates'
STATIC_DIR = BASE_DIR / 'static'

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from afpub_to_markdown import (
    _analyze_styles,
    _convert,
    _decompress_afpub,
    _load_styles_yaml,
    _load_zstd,
)

try:
    from pdf_to_markdown import (
        _convert_pdf as _pdf_convert,
        _dump_fonts as _pdf_dump_fonts,
        _load_pdf_styles,
    )
    _PDF_AVAILABLE = True
except ImportError:
    _PDF_AVAILABLE = False
    print('WARNING: pdf_to_markdown not available (PyMuPDF may not be installed).')

_ZSTD = _load_zstd()
if _ZSTD is None:
    print('ERROR: libzstd not found.')
    sys.exit(1)

GCS_BUCKET = os.environ.get('GCS_BUCKET', 'affinity-markdown-uploads')
_sa_credentials = None
_gcs_client = None


def _get_sa_credentials():
    global _sa_credentials
    if _sa_credentials is None:
        raw = os.environ.get('GCP_SA_KEY_B64', '')
        if not raw:
            raise RuntimeError('GCP_SA_KEY_B64 env var not set')
        import google.oauth2.service_account as sa
        info = json.loads(base64.b64decode(raw).decode('utf-8'))
        _sa_credentials = sa.Credentials.from_service_account_info(
            info,
            scopes=['https://www.googleapis.com/auth/devstorage.read_write'],
        )
    return _sa_credentials


def _get_gcs():
    global _gcs_client
    if _gcs_client is None:
        try:
            from google.cloud import storage
            _gcs_client = storage.Client(credentials=_get_sa_credentials())
            print('GCS client initialised')
        except Exception as e:
            print(f'GCS unavailable: {e}')
    return _gcs_client


def _maybe_delete(gcs, object_name: str):
    """Delete a GCS object unless it lives in the dev/ folder."""
    if object_name.startswith('dev/'):
        return
    try:
        gcs.bucket(GCS_BUCKET).blob(object_name).delete()
    except Exception:
        pass


def _signed_upload_url(object_name: str) -> str:
    from google.cloud import storage
    creds = _get_sa_credentials()
    client = storage.Client(credentials=creds)
    blob = client.bucket(GCS_BUCKET).blob(object_name)
    return blob.generate_signed_url(
        version='v4',
        expiration=datetime.timedelta(hours=1),
        method='PUT',
        content_type='application/octet-stream',
    )


def _signed_download_url(object_name: str) -> str:
    from google.cloud import storage
    creds = _get_sa_credentials()
    client = storage.Client(credentials=creds)
    blob = client.bucket(GCS_BUCKET).blob(object_name)
    return blob.generate_signed_url(
        version='v4',
        expiration=datetime.timedelta(hours=1),
        method='GET',
    )


# ────────────────────────────────────────────────────────────────────────────────
# AFPUB helpers
# ────────────────────────────────────────────────────────────────────────────────

def _run_analyze(input_path: Path, template: str | None) -> str:
    """Run _analyze_styles and return the output as a string."""
    if template:
        styles_path = TEMPLATES_DIR / template / 'styles.yaml'
        if styles_path.exists():
            style_map, name_map, _ = _load_styles_yaml(styles_path)
        else:
            style_map, name_map = {}, {}
    else:
        style_map, name_map = {}, {}
    buf = io.StringIO()
    with redirect_stdout(buf):
        _analyze_styles(input_path, style_map, name_map, _ZSTD)
    return buf.getvalue()


def _run_convert(input_path: Path, output_path: Path, template: str) -> None:
    """Load afpub styles and run conversion."""
    styles_path = TEMPLATES_DIR / template / 'styles.yaml'
    if not styles_path.exists():
        raise FileNotFoundError(f"Template '{template}' not found.")
    style_map, name_map, fallback = _load_styles_yaml(styles_path)
    _convert(input_path, output_path, style_map, name_map, fallback, _ZSTD)


# ────────────────────────────────────────────────────────────────────────────────
# PDF helpers
# ────────────────────────────────────────────────────────────────────────────────

def _run_convert_pdf(input_path: Path, output_path: Path, template: str | None) -> None:
    """Load pdf_styles and run PDF conversion."""
    if not _PDF_AVAILABLE:
        raise RuntimeError('PDF conversion not available (PyMuPDF not installed).')
    font_map: dict = {}
    fallback = 'warn'
    if template:
        styles_path = TEMPLATES_DIR / template / 'pdf_styles.yaml'
        if styles_path.exists():
            font_map, fallback = _load_pdf_styles(styles_path)
    _pdf_convert(input_path, output_path, font_map, fallback)


def _run_analyze_pdf(input_path: Path, template: str | None) -> str:
    """Run _dump_fonts and return the output as a string."""
    if not _PDF_AVAILABLE:
        raise RuntimeError('PDF analysis not available (PyMuPDF not installed).')
    buf = io.StringIO()
    with redirect_stdout(buf):
        _pdf_dump_fonts(input_path)
    return buf.getvalue()


# ────────────────────────────────────────────────────────────────────────────────
# App
# ────────────────────────────────────────────────────────────────────────────────

app = FastAPI(title='Affinity to Markdown Converter App')
app.mount('/static', StaticFiles(directory=str(STATIC_DIR)), name='static')


@app.on_event('startup')
async def startup():
    _get_gcs()


@app.get('/', response_class=HTMLResponse)
async def root():
    return HTMLResponse(content=(STATIC_DIR / 'index.html').read_text(encoding='utf-8'))


@app.get('/api/templates')
async def list_templates():
    if not TEMPLATES_DIR.exists():
        return JSONResponse({'templates': []})
    names = sorted(
        d.name for d in TEMPLATES_DIR.iterdir()
        if d.is_dir() and (d / 'styles.yaml').exists()
    )
    return JSONResponse({'templates': names})


# ── Shared large-file upload URL ─────────────────────────────────────────────────

@app.post('/api/request-upload')
async def request_upload(request: Request):
    body = await request.json()
    filename = body.get('filename', 'upload.bin')
    ext = Path(filename).suffix.lower()
    if ext not in ('.afpub', '.pdf'):
        raise HTTPException(status_code=400, detail='File must be a .afpub or .pdf file.')
    object_name = f'uploads/{uuid.uuid4().hex}/{filename}'
    try:
        url = _signed_upload_url(object_name)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f'Could not generate upload URL: {exc}')
    return JSONResponse({'upload_url': url, 'object_name': object_name})


# ── AFPUB endpoints ────────────────────────────────────────────────────────────────

@app.post('/api/convert')
async def convert(file: UploadFile = File(...), template: str = Form(...)):
    if not file.filename or not file.filename.lower().endswith('.afpub'):
        raise HTTPException(status_code=400, detail='File must be a .afpub file.')
    styles_path = TEMPLATES_DIR / template / 'styles.yaml'
    if not styles_path.exists():
        raise HTTPException(status_code=400, detail=f"Template '{template}' not found.")
    with tempfile.TemporaryDirectory() as tmp:
        input_path = Path(tmp) / file.filename
        output_path = Path(tmp) / (Path(file.filename).stem + '.md')
        input_path.write_bytes(await file.read())
        try:
            _run_convert(input_path, output_path, template)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f'Conversion failed: {exc}')
        if not output_path.exists():
            raise HTTPException(status_code=500, detail='Conversion produced no output.')
        md_content = output_path.read_text(encoding='utf-8')
    stem = Path(file.filename).stem
    tmp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8')
    tmp_file.write(md_content)
    tmp_file.close()
    return FileResponse(
        path=tmp_file.name,
        filename=stem + '.md',
        media_type='text/markdown',
        headers={'Content-Disposition': f'attachment; filename="{stem}.md"'},
    )


@app.post('/api/analyze-styles')
async def analyze_styles_direct(file: UploadFile = File(...), template: str = Form(default='')):
    if not file.filename or not file.filename.lower().endswith('.afpub'):
        raise HTTPException(status_code=400, detail='File must be a .afpub file.')
    with tempfile.TemporaryDirectory() as tmp:
        input_path = Path(tmp) / file.filename
        input_path.write_bytes(await file.read())
        try:
            result = _run_analyze(input_path, template or None)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f'Analysis failed: {exc}')
    return PlainTextResponse(result)


@app.post('/api/convert-from-gcs')
async def convert_from_gcs(request: Request):
    body = await request.json()
    object_name = body.get('object_name', '')
    filename = object_name.split('/')[-1]
    template = body.get('template', '')
    if not filename.lower().endswith('.afpub'):
        raise HTTPException(status_code=400, detail='File must be a .afpub file.')
    styles_path = TEMPLATES_DIR / template / 'styles.yaml'
    if not styles_path.exists():
        raise HTTPException(status_code=400, detail=f"Template '{template}' not found.")
    gcs = _get_gcs()
    if not gcs:
        raise HTTPException(status_code=500, detail='GCS not available.')
    with tempfile.TemporaryDirectory() as tmp:
        input_path = Path(tmp) / filename
        output_path = Path(tmp) / (Path(filename).stem + '.md')
        try:
            gcs.bucket(GCS_BUCKET).blob(object_name).download_to_filename(str(input_path))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f'GCS download failed: {exc}')
        try:
            _run_convert(input_path, output_path, template)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f'Conversion failed: {exc}')
        finally:
            _maybe_delete(gcs, object_name)
        if not output_path.exists():
            raise HTTPException(status_code=500, detail='Conversion produced no output.')
        md_content = output_path.read_text(encoding='utf-8')
    stem = Path(filename).stem
    tmp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8')
    tmp_file.write(md_content)
    tmp_file.close()
    return FileResponse(
        path=tmp_file.name,
        filename=stem + '.md',
        media_type='text/markdown',
        headers={'Content-Disposition': f'attachment; filename="{stem}.md"'},
    )


@app.post('/api/analyze-from-gcs')
async def analyze_from_gcs(request: Request):
    body = await request.json()
    object_name = body.get('object_name', '')
    filename = object_name.split('/')[-1]
    template = body.get('template', '')
    if not filename.lower().endswith('.afpub'):
        raise HTTPException(status_code=400, detail='File must be a .afpub file.')
    gcs = _get_gcs()
    if not gcs:
        raise HTTPException(status_code=500, detail='GCS not available.')
    with tempfile.TemporaryDirectory() as tmp:
        input_path = Path(tmp) / filename
        try:
            gcs.bucket(GCS_BUCKET).blob(object_name).download_to_filename(str(input_path))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f'GCS download failed: {exc}')
        try:
            result = _run_analyze(input_path, template or None)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f'Analysis failed: {exc}')
        finally:
            _maybe_delete(gcs, object_name)
    return PlainTextResponse(result)


# ── PDF endpoints ──────────────────────────────────────────────────────────────────

@app.post('/api/convert-pdf')
async def convert_pdf(file: UploadFile = File(...), template: str = Form(default='')):
    if not file.filename or not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail='File must be a .pdf file.')
    if not _PDF_AVAILABLE:
        raise HTTPException(status_code=503, detail='PDF conversion not available (PyMuPDF not installed).')
    with tempfile.TemporaryDirectory() as tmp:
        input_path = Path(tmp) / file.filename
        output_path = Path(tmp) / (Path(file.filename).stem + '.md')
        input_path.write_bytes(await file.read())
        try:
            _run_convert_pdf(input_path, output_path, template or None)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f'Conversion failed: {exc}')
        if not output_path.exists():
            raise HTTPException(status_code=500, detail='Conversion produced no output.')
        md_content = output_path.read_text(encoding='utf-8')
    stem = Path(file.filename).stem
    tmp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8')
    tmp_file.write(md_content)
    tmp_file.close()
    return FileResponse(
        path=tmp_file.name,
        filename=stem + '.md',
        media_type='text/markdown',
        headers={'Content-Disposition': f'attachment; filename="{stem}.md"'},
    )


@app.post('/api/analyze-pdf-fonts')
async def analyze_pdf_fonts(file: UploadFile = File(...), template: str = Form(default='')):
    if not file.filename or not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail='File must be a .pdf file.')
    if not _PDF_AVAILABLE:
        raise HTTPException(status_code=503, detail='PDF analysis not available (PyMuPDF not installed).')
    with tempfile.TemporaryDirectory() as tmp:
        input_path = Path(tmp) / file.filename
        input_path.write_bytes(await file.read())
        try:
            result = _run_analyze_pdf(input_path, template or None)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f'Analysis failed: {exc}')
    return PlainTextResponse(result)


@app.post('/api/convert-pdf-from-gcs')
async def convert_pdf_from_gcs(request: Request):
    body = await request.json()
    object_name = body.get('object_name', '')
    filename = object_name.split('/')[-1]
    template = body.get('template', '')
    if not filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail='File must be a .pdf file.')
    if not _PDF_AVAILABLE:
        raise HTTPException(status_code=503, detail='PDF conversion not available (PyMuPDF not installed).')
    gcs = _get_gcs()
    if not gcs:
        raise HTTPException(status_code=500, detail='GCS not available.')
    with tempfile.TemporaryDirectory() as tmp:
        input_path = Path(tmp) / filename
        output_path = Path(tmp) / (Path(filename).stem + '.md')
        try:
            gcs.bucket(GCS_BUCKET).blob(object_name).download_to_filename(str(input_path))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f'GCS download failed: {exc}')
        try:
            _run_convert_pdf(input_path, output_path, template or None)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f'Conversion failed: {exc}')
        finally:
            _maybe_delete(gcs, object_name)
        if not output_path.exists():
            raise HTTPException(status_code=500, detail='Conversion produced no output.')
        md_content = output_path.read_text(encoding='utf-8')
    stem = Path(filename).stem
    tmp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8')
    tmp_file.write(md_content)
    tmp_file.close()
    return FileResponse(
        path=tmp_file.name,
        filename=stem + '.md',
        media_type='text/markdown',
        headers={'Content-Disposition': f'attachment; filename="{stem}.md"'},
    )


@app.post('/api/analyze-pdf-fonts-from-gcs')
async def analyze_pdf_fonts_from_gcs(request: Request):
    body = await request.json()
    object_name = body.get('object_name', '')
    filename = object_name.split('/')[-1]
    template = body.get('template', '')
    if not filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail='File must be a .pdf file.')
    if not _PDF_AVAILABLE:
        raise HTTPException(status_code=503, detail='PDF analysis not available (PyMuPDF not installed).')
    gcs = _get_gcs()
    if not gcs:
        raise HTTPException(status_code=500, detail='GCS not available.')
    with tempfile.TemporaryDirectory() as tmp:
        input_path = Path(tmp) / filename
        try:
            gcs.bucket(GCS_BUCKET).blob(object_name).download_to_filename(str(input_path))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f'GCS download failed: {exc}')
        try:
            result = _run_analyze_pdf(input_path, template or None)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f'Analysis failed: {exc}')
        finally:
            _maybe_delete(gcs, object_name)
    return PlainTextResponse(result)


# ── Dev / misc endpoints ──────────────────────────────────────────────────────────

@app.post('/api/dev/signed-download')
async def dev_signed_download(request: Request):
    """Generate a signed download URL for a file in the dev/ folder."""
    body = await request.json()
    object_name = body.get('object_name', '')
    if not object_name.startswith('dev/'):
        raise HTTPException(status_code=400, detail='Only dev/ objects are accessible via this endpoint.')
    try:
        url = _signed_download_url(object_name)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f'Could not generate download URL: {exc}')
    return JSONResponse({'download_url': url})


HOST = '0.0.0.0'
PORT = int(os.environ.get('PORT', 8080))


def main():
    uvicorn.run(app, host=HOST, port=PORT, log_level='warning')


if __name__ == '__main__':
    main()
