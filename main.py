import io
import json
import os
import sys
import tempfile
import uuid
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
    _convert,
    _decompress_afpub,
    _dump_styles,
    _load_styles_yaml,
    _load_zstd,
)

_ZSTD = _load_zstd()
if _ZSTD is None:
    print('ERROR: libzstd not found.')
    sys.exit(1)

GCS_BUCKET = os.environ.get('GCS_BUCKET', 'affinity-markdown-uploads')
_gcs_client = None
_signing_credentials = None


def _get_gcs():
    global _gcs_client
    if _gcs_client is None:
        try:
            from google.cloud import storage
            _gcs_client = storage.Client()
            bucket = _gcs_client.bucket(GCS_BUCKET)
            bucket.cors = [{
                'origin': ['*'],
                'method': ['PUT', 'GET', 'HEAD', 'OPTIONS'],
                'responseHeader': ['Content-Type', 'Content-Length', 'ETag'],
                'maxAgeSeconds': 3600,
            }]
            bucket.patch()
            print('GCS client initialised + CORS configured')
        except Exception as e:
            print(f'GCS unavailable: {e}')
    return _gcs_client


def _get_signing_credentials():
    """
    Return service account credentials that can sign URLs.
    Uses GCP_SA_KEY env var (the JSON key injected by GitHub Actions).
    Signed URLs are the only CORS-safe way for browsers to PUT directly
    to GCS — resumable session URLs don't respect bucket CORS policies.
    """
    global _signing_credentials
    if _signing_credentials is None:
        sa_key_json = os.environ.get('GCP_SA_KEY', '')
        if not sa_key_json:
            raise RuntimeError('GCP_SA_KEY env var not set')
        import google.oauth2.service_account as sa
        info = json.loads(sa_key_json)
        _signing_credentials = sa.Credentials.from_service_account_info(
            info,
            scopes=['https://www.googleapis.com/auth/devstorage.read_write'],
        )
    return _signing_credentials


def _make_signed_upload_url(object_name: str) -> str:
    """
    Generate a V4 signed URL for a browser PUT.
    Signed URLs are CORS-safe: the auth is baked in, no session handshake needed.
    Expires in 1 hour (plenty for any upload).
    """
    import datetime
    from google.cloud import storage
    creds = _get_signing_credentials()
    client = storage.Client(credentials=creds)
    bucket = client.bucket(GCS_BUCKET)
    blob = bucket.blob(object_name)
    url = blob.generate_signed_url(
        version='v4',
        expiration=datetime.timedelta(hours=1),
        method='PUT',
        content_type='application/octet-stream',
    )
    return url


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


@app.post('/api/convert')
async def convert(file: UploadFile = File(...), template: str = Form(...)):
    if not file.filename or not file.filename.lower().endswith('.afpub'):
        raise HTTPException(status_code=400, detail='File must be a .afpub file.')
    styles_path = TEMPLATES_DIR / template / 'styles.yaml'
    if not styles_path.exists():
        raise HTTPException(status_code=400, detail=f"Template '{template}' not found.")
    style_map, fallback = _load_styles_yaml(styles_path)
    with tempfile.TemporaryDirectory() as tmp:
        input_path = Path(tmp) / file.filename
        output_path = Path(tmp) / (Path(file.filename).stem + '.md')
        input_path.write_bytes(await file.read())
        try:
            _convert(input_path, output_path, style_map, fallback, _ZSTD)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f'Conversion failed: {exc}')
        if not output_path.exists():
            raise HTTPException(status_code=500, detail='Conversion produced no output.')
        md_content = output_path.read_text(encoding='utf-8')
    tmp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8')
    tmp_file.write(md_content)
    tmp_file.close()
    return FileResponse(
        path=tmp_file.name,
        filename=Path(file.filename).stem + '.md',
        media_type='text/markdown',
        headers={'Content-Disposition': f'attachment; filename="{Path(file.filename).stem}.md"'},
    )


@app.post('/api/initiate-upload')
async def initiate_upload(request: Request):
    """
    Return a V4 signed URL for the browser to PUT to directly.
    Signed URLs are CORS-safe; resumable session URLs are not.
    """
    body = await request.json()
    filename = body.get('filename', 'upload.afpub')
    if not filename.lower().endswith('.afpub'):
        raise HTTPException(status_code=400, detail='File must be a .afpub file.')

    object_name = f'uploads/{uuid.uuid4().hex}/{filename}'
    try:
        signed_url = _make_signed_upload_url(object_name)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f'Upload initiation failed: {exc}')

    return JSONResponse({'session_uri': signed_url, 'object_name': object_name})


@app.post('/api/convert-from-gcs')
async def convert_from_gcs(request: Request):
    body = await request.json()
    object_name = body.get('object_name', '')
    filename = body.get('filename', 'upload.afpub')
    template = body.get('template', '')
    if not filename.lower().endswith('.afpub'):
        raise HTTPException(status_code=400, detail='File must be a .afpub file.')
    styles_path = TEMPLATES_DIR / template / 'styles.yaml'
    if not styles_path.exists():
        raise HTTPException(status_code=400, detail=f"Template '{template}' not found.")
    style_map, fallback = _load_styles_yaml(styles_path)
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
            _convert(input_path, output_path, style_map, fallback, _ZSTD)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f'Conversion failed: {exc}')
        finally:
            try: gcs.bucket(GCS_BUCKET).blob(object_name).delete()
            except Exception: pass
        if not output_path.exists():
            raise HTTPException(status_code=500, detail='Conversion produced no output.')
        md_content = output_path.read_text(encoding='utf-8')
    tmp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8')
    tmp_file.write(md_content)
    tmp_file.close()
    return FileResponse(
        path=tmp_file.name,
        filename=Path(filename).stem + '.md',
        media_type='text/markdown',
        headers={'Content-Disposition': f'attachment; filename="{Path(filename).stem}.md"'},
    )


@app.post('/api/dump-from-gcs')
async def dump_from_gcs(request: Request):
    body = await request.json()
    object_name = body.get('object_name', '')
    filename = body.get('filename', 'upload.afpub')
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
        buf = io.StringIO()
        try:
            from contextlib import redirect_stdout
            data = _decompress_afpub(input_path, _ZSTD)
            with redirect_stdout(buf):
                _dump_styles(data)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f'Dump failed: {exc}')
        finally:
            try: gcs.bucket(GCS_BUCKET).blob(object_name).delete()
            except Exception: pass
    return PlainTextResponse(buf.getvalue())


HOST = '0.0.0.0'
PORT = int(os.environ.get('PORT', 8080))


def main():
    uvicorn.run(app, host=HOST, port=PORT, log_level='warning')


if __name__ == '__main__':
    main()
