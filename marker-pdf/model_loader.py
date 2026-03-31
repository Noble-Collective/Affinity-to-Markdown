"""
model_loader.py — Model loading for the Marker PDF converter.

Loads all 5 Marker/Surya models synchronously before uvicorn starts.
All models are kept in memory — even with disable_ocr=True, Marker
still accesses model objects internally during the pipeline.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

_models: Optional[dict] = None
_load_error: Optional[str] = None


def models_ready() -> bool:
    return _models is not None


def load_error() -> Optional[str]:
    return _load_error


def get_models() -> dict:
    if _models is None:
        raise RuntimeError("Models not loaded yet")
    return _models


def load_sync() -> None:
    """
    Load all Marker/Surya models synchronously.
    Blocks until complete. Called once at startup before uvicorn starts.
    """
    global _models, _load_error
    try:
        import torch
        from marker.models import create_model_dict

        logger.info("Loading all Marker models...")
        models = create_model_dict(device="cpu", dtype=torch.float32)
        _models = models
        logger.info(f"Models ready: {list(models.keys())}")

    except Exception as e:
        msg = f"Model loading failed: {e}"
        logger.error(msg, exc_info=True)
        _load_error = msg


def start_loading() -> None:
    """No-op — kept for backwards compatibility."""
    pass
