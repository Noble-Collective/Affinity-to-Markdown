"""
model_loader.py — Model loading for the Marker PDF converter.

Provides both synchronous (load_sync) and async-friendly accessors.
load_sync() is called from app.py __main__ BEFORE uvicorn starts,
so models are always ready when the first request arrives.
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
    Frees the three unused models after loading to stay within 8 GB RAM.
    Blocks until complete. Called once at startup before uvicorn starts.
    """
    global _models, _load_error
    try:
        import torch
        from marker.models import create_model_dict

        logger.info("Loading models via create_model_dict()...")
        models = create_model_dict(device="cpu", dtype=torch.float32)
        logger.info(f"All models loaded: {list(models.keys())}")

        # Free unused models to reduce steady-state RAM
        for unused in ("recognition_model", "table_rec_model", "ocr_error_model"):
            if unused in models:
                models[unused] = None
                logger.info(f"Freed unused model: {unused}")

        _models = models
        active = [k for k, v in models.items() if v is not None]
        logger.info(f"Models ready (active): {active}")

    except Exception as e:
        msg = f"Model loading failed: {e}"
        logger.error(msg, exc_info=True)
        _load_error = msg


# Keep start_loading() as a no-op for backwards compatibility
def start_loading() -> None:
    pass
