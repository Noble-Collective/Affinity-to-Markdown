"""Marker PDF → Markdown conversion service.

Routing only — business logic lives in converter.py and gcs_client.py.
Models load in a background thread at startup so the health check
passes immediately and Cloud Run doesn't time out waiting for readiness.
"""
import logging
import os

import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import JSONResponse

import model_loader

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Kick off model loading in background immediately at startup.
    # The health check returns 200 right away; /status shows when ready.
    model_loader.start_loading()
    yield
    # Shutdown: nothing to clean up (models released with process)


app = FastAPI(
    title="Marker PDF Converter",
    description="Converts PDF files to Markdown using the Marker library.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> JSONResponse:
    """Liveness probe — always returns 200 so Cloud Run doesn't kill the instance
    while models are still loading in the background."""
    return JSONResponse({"status": "ok", "service": "marker-pdf-converter"})


@app.get("/status")
async def status() -> JSONResponse:
    """Readiness check — tells clients whether models are loaded and ready."""
    if model_loader.models_ready():
        return JSONResponse({"ready": True, "models": "loaded"})
    if model_loader.load_error():
        return JSONResponse(
            {"ready": False, "error": model_loader.load_error()}, status_code=500
        )
    return JSONResponse({"ready": False, "status": "loading"}, status_code=503)


# ── conversion endpoints will be added here in chunk 2 ─────────────────────


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8080)),
        log_level="info",
    )
