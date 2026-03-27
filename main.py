import io
import os
import sys
import tempfile
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

app = FastAPI(title='Affinity to Markdown Converter App')
app.mount('/static', StaticFiles(directory=str(STATIC_DIR)), name='static')


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


@app.post('/api/dump-styles')
async def dump_styles(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith('.afpub'):
        raise HTTPException(status_code=400, detail='File must be a .afpub file.')
    with tempfile.TemporaryDirectory() as tmp:
        input_path = Path(tmp) / file.filename
        input_path.write_bytes(await file.read())
        buf = io.StringIO()
        try:
            from contextlib import redirect_stdout
            data = _decompress_afpub(input_path, _ZSTD)
            with redirect_stdout(buf):
                _dump_styles(data)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f'Dump failed: {exc}')
    return PlainTextResponse(buf.getvalue())


HOST = '0.0.0.0'
PORT = int(os.environ.get('PORT', 8080))


def main():
    uvicorn.run(app, host=HOST, port=PORT, log_level='warning')


if __name__ == '__main__':
    main()
