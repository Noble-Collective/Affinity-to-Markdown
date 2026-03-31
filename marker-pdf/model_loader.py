"""
model_loader.py — Thread-safe singleton for Marker/Surya model loading.

Only loads the models actually needed for our trimmed processor list:
  - layout_model:    Required by LayoutBuilder (core layout detection)
  - detection_model: Required by LineBuilder (text line detection)

Skipped (not needed with disable_ocr=True and no table/equation processors):
  - recognition_model: OCR text recognition (we use embedded PDF text)
  - table_rec_model:   Table structure (TableProcessor removed)
  - ocr_error_model:   OCR error correction (OCR disabled)

This cuts peak RAM from ~10 GB down to ~4 GB, fitting within 8 GB Cloud Run.
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


def _load_minimal_models() -> dict:
    """
    Load only the two models needed for layout + line detection.
    Skips OCR, table, and error-correction models.
    """
    import torch
    from surya.layout import LayoutPredictor
    from surya.detection import DetectionPredictor
    from surya.common.surya.schema import TaskNames
    from surya.common.predictor import FoundationPredictor
    from surya.settings import settings as surya_settings

    device = "cpu"
    dtype = torch.float32

    logger.info("Loading layout_model...")
    layout_model = LayoutPredictor(
        FoundationPredictor(
            checkpoint=surya_settings.LAYOUT_MODEL_CHECKPOINT,
            device=device,
            dtype=dtype,
        )
    )

    logger.info("Loading detection_model...")
    detection_model = DetectionPredictor(device=device, dtype=dtype)

    return {
        "layout_model": layout_model,
        "detection_model": detection_model,
        # These keys must exist in the dict even if unused,
        # because PdfConverter checks for them by name.
        "recognition_model": None,
        "table_rec_model": None,
        "ocr_error_model": None,
    }


def _do_load() -> None:
    global _models, _load_error, _loading
    try:
        logger.info("Loading minimal model set (layout + detection only)...")
        models = _load_minimal_models()
        with _lock:
            _models = models
            _loading = False
        logger.info(f"Models ready: {[k for k, v in models.items() if v is not None]}")
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
