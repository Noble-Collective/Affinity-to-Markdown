"""
app.py — Marker PDF → Markdown conversion service.

Routing only — business logic lives in converter.py.
Models load in a background thread at startup so Cloud Run's
health check passes immediately while models are downloading.
"""
import logging
import os
import tempfile
from pathlib import Path

import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

import model_loader
from converter import convert_pdf, parse_page_range

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DIRECT_LIMIT = 30 * 1024 * 1024  # 30 MB — files larger than this use GCS (chunk 3)


@asynccontextmanager
async def lifespan(app: FastAPI):
    model_loader.start_loading()
    yield


app = FastAPI(
    title="Marker PDF Converter",
    description="Converts PDF files to Markdown using the Marker library.",
    version="0.2.0",
    lifespan=lifespan,
)


# ── Health / readiness ───────────────────────────────────────────────────────

@app.get("/health")
async def health() -> JSONResponse:
    """Liveness probe — always 200. Cloud Run won't kill the instance
    while models download in the background."""
    return JSONResponse({"status": "ok", "service": "marker-pdf-converter"})


@app.get("/status")
async def status() -> JSONResponse:
    """Readiness check — shows whether models are loaded and ready."""
    if model_loader.models_ready():
        return JSONResponse({"ready": True, "models": "loaded"})
    if model_loader.load_error():
        return JSONResponse(
            {"ready": False, "error": model_loader.load_error()}, status_code=500
        )
    return JSONResponse({"ready": False, "status": "loading"}, status_code=503)


# ── Conversion (direct upload, ≤30 MB) ────────────────────────────────────────

@app.post("/convert")
async def convert(
    file: UploadFile = File(...),
    page_range: str = Form(default=""),
) -> FileResponse:
    """
    Convert an uploaded PDF to Markdown.

    - file:       PDF file, max 30 MB (larger files use /convert-from-gcs, chunk 3)
    - page_range: Optional page range, e.g. "62-200" or "0-10,20-30" (0-indexed)
                  Useful for skipping front matter in long documents.
    """
    if not model_loader.models_ready():
        raise HTTPException(
            status_code=503,
            detail="Models are still loading — try again in a few minutes.",
        )

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a .pdf file.")

    # Parse optional page range
    pages = None
    if page_range.strip():
        try:
            pages = parse_page_range(page_range.strip())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid page_range: {exc}")

    content = await file.read()
    if len(content) > DIRECT_LIMIT:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds 30 MB direct limit. Use /convert-from-gcs for large files.",
        )

    with tempfile.TemporaryDirectory() as tmp:
        input_path = Path(tmp) / file.filename
        input_path.write_bytes(content)
        try:
            markdown = convert_pdf(input_path, page_range=pages)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        except Exception as exc:
            logger.exception("Conversion failed")
            raise HTTPException(status_code=500, detail=f"Conversion failed: {exc}")

    stem = Path(file.filename).stem
    tmp_out = tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    )
    tmp_out.write(markdown)
    tmp_out.close()

    return FileResponse(
        path=tmp_out.name,
        filename=stem + ".md",
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{stem}.md"'},
    )


# ── GCS-based conversion will be added here in chunk 3 ─────────────────────


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8080)),
        log_level="info",
    )
