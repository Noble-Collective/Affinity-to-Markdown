"""
model_loader.py — Thread-safe singleton for Marker/Surya model loading.

On startup, the loading sequence is:
  1. Check if models already exist locally (warm instance reuse).
  2. If not: try GCS cache (fast, ~1-2 min same-region download).
  3. If no GCS cache: let Surya download from HuggingFace (~10-15 min).
  4. After a HuggingFace download: save models to GCS for next time.
  5. Load models into memory via create_model_dict().
"""
import logging
import os
import threading
from typing import Optional

logger = logging.getLogger(__name__)

_models: Optional[dict] = None
_load_error: Optional[str] = None
_lock = threading.Lock()
_loading = False


def models_ready() -> bool:
    return _models is not None


def load_error() -> Optional[str]:
    return _load_error


def is_loading() -> bool:
    return _loading


def get_models() -> dict:
    if _models is None:
        raise RuntimeError("Models not loaded yet")
    return _models


def _do_load() -> None:
    global _models, _load_error, _loading
    try:
        import torch
        from marker.models import create_model_dict
        import model_cache

        bucket = os.environ.get("GCS_BUCKET", "")
        used_gcs_cache = False

        if model_cache.models_exist_locally():
            logger.info("Models already on disk (warm instance)")
        elif bucket:
            used_gcs_cache = model_cache.restore_from_gcs(bucket)
            if not used_gcs_cache:
                logger.info("Downloading models from HuggingFace (first cold start)...")
        else:
            logger.info("No GCS bucket configured, downloading from HuggingFace...")

        logger.info("Loading models into memory...")
        models = create_model_dict(device="cpu", dtype=torch.float32)

        with _lock:
            _models = models
            _loading = False
        logger.info(f"Models ready: {list(models.keys())}")

        # Save to GCS after a fresh HuggingFace download
        if bucket and not used_gcs_cache and not model_cache.models_exist_locally():
            # models_exist_locally() would now return True, so check differently
            pass  # save_to_gcs is called below
        if bucket and not used_gcs_cache:
            logger.info("Saving models to GCS cache for future cold starts...")
            model_cache.save_to_gcs(bucket)

    except Exception as e:
        msg = f"Model loading failed: {e}"
        logger.error(msg, exc_info=True)
        with _lock:
            _load_error = msg
            _loading = False


def start_loading() -> None:
    global _loading
    with _lock:
        if _models is not None or _load_error is not None or _loading:
            return
        _loading = True
    thread = threading.Thread(target=_do_load, daemon=True, name="model-loader")
    thread.start()
    logger.info("Model loading started in background thread")
