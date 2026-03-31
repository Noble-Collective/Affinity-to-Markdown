"""
model_loader.py — Thread-safe singleton for Marker/Surya model loading.

Models are downloaded and loaded once in a background thread at startup.
The rest of the app checks `models_ready()` before attempting conversion.
"""
import os
import threading
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Pin cache dirs before any torch/HF imports happen
os.environ.setdefault("HF_HOME", "/app/models")
os.environ.setdefault("TORCH_HOME", "/app/models/torch")
os.environ.setdefault("TRANSFORMERS_CACHE", "/app/models/transformers")

_models: Optional[dict] = None
_load_error: Optional[str] = None
_lock = threading.Lock()
_loading = False


def models_ready() -> bool:
    """Return True if models have been loaded successfully."""
    return _models is not None


def load_error() -> Optional[str]:
    """Return the error message if model loading failed, else None."""
    return _load_error


def is_loading() -> bool:
    """Return True if models are currently being loaded."""
    return _loading


def get_models() -> dict:
    """Return the loaded model dict. Raises if not ready."""
    if _models is None:
        raise RuntimeError("Models not loaded yet")
    return _models


def _do_load() -> None:
    """Internal: download and load models. Runs in a background thread."""
    global _models, _load_error, _loading
    try:
        logger.info("Starting Marker model download/load...")
        import torch
        from marker.models import create_model_dict

        models = create_model_dict(device="cpu", dtype=torch.float32)
        with _lock:
            _models = models
            _loading = False
        logger.info(f"Models ready: {list(models.keys())}")
    except Exception as e:
        msg = f"Model loading failed: {e}"
        logger.error(msg)
        with _lock:
            _load_error = msg
            _loading = False


def start_loading() -> None:
    """Kick off background model loading. Safe to call multiple times."""
    global _loading
    with _lock:
        if _models is not None or _load_error is not None or _loading:
            return
        _loading = True
    thread = threading.Thread(target=_do_load, daemon=True, name="model-loader")
    thread.start()
    logger.info("Model loading started in background thread")
