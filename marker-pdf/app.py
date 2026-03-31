"""Marker PDF → Markdown conversion service.

Routing only — business logic lives in converter.py and gcs_client.py.
"""
import os
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(
    title="Marker PDF Converter",
    description="Converts PDF files to Markdown using the Marker library.",
    version="0.1.0",
)


@app.get("/health")
async def health() -> JSONResponse:
    """Liveness / readiness probe for Cloud Run."""
    return JSONResponse({
        "status": "ok",
        "service": "marker-pdf-converter",
        "version": "0.1.0",
    })


# ── future endpoints will be imported and registered here ────────────────────
# from routes.convert import router as convert_router
# app.include_router(convert_router)


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8080)),
        log_level="info",
    )
