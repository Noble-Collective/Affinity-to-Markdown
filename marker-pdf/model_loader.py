"""
model_loader.py — Thread-safe singleton for Marker/Surya model loading.

Loads all models via create_model_dict() then immediately frees the three
we don't need (recognition, table_rec, ocr_error) to stay within 8 GB RAM.

With disable_ocr=True and TableProcessor removed, only layout_model and
detection_model are actually used during conversion.
"""
import logging
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

        logger.info("Loading models via create_model_dict() ...")
        models = create_model_dict(device="cpu", dtype=torch.float32)
        logger.info(f"All models loaded: {list(models.keys())}")

        # Free the three models we don't use:
        #   recognition_model: OCR text recognition  (disable_ocr=True)
        #   table_rec_model:   Table structure        (TableProcessor removed)
        #   ocr_error_model:   OCR error correction   (OCR disabled)
        # Setting to None releases the PyTorch tensors and frees RAM.
        for unused in ("recognition_model", "table_rec_model", "ocr_error_model"):
            if unused in models:
                logger.info(f"Freeing unused model: {unused}")
                models[unused] = None

        with _lock:
            _models = models
            _loading = False

        active = [k for k, v in models.items() if v is not None]
        logger.info(f"Models ready (active): {active}")

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
