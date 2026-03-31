"""
model_cache.py — GCS-backed model cache for Surya/Marker models.

Surya downloads models to /root/.cache/datalab/models/ at runtime.
This module wraps that download with a GCS cache so cold starts
download from GCS (~1-2 min, same region) instead of HuggingFace
(~10-15 min, external).

Flow:
  1. Cold start: check if models already exist locally (warm instance).
  2. If not: try to restore from GCS cache.
  3. If GCS cache is missing: let Surya download normally from HuggingFace.
  4. After any HuggingFace download: upload to GCS for next time.
"""
import logging
import os
import shutil
import tarfile
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Where Surya stores its models (discovered from Cloud Run logs)
SURYA_CACHE_DIR = Path("/root/.cache/datalab/models")

# GCS object name for the packed model archive
GCS_MODEL_OBJECT = "model-cache/surya-models.tar.gz"


def _get_gcs_client():
    """Return a GCS client using the service account key env var."""
    import base64
    import json
    import google.oauth2.service_account as sa
    from google.cloud import storage

    raw = os.environ.get("GCP_SA_KEY_B64", "")
    if not raw:
        raise RuntimeError("GCP_SA_KEY_B64 env var not set")
    info = json.loads(base64.b64decode(raw).decode("utf-8"))
    creds = sa.Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/devstorage.read_write"],
    )
    return storage.Client(credentials=creds)


def models_exist_locally() -> bool:
    """Return True if Surya model files are already on disk."""
    if not SURYA_CACHE_DIR.exists():
        return False
    # A rough check: at least one subdirectory with files in it
    subdirs = [d for d in SURYA_CACHE_DIR.iterdir() if d.is_dir()]
    return len(subdirs) >= 3  # layout, text_recognition, detection at minimum


def restore_from_gcs(bucket_name: str) -> bool:
    """
    Try to download the model archive from GCS and unpack it.
    Returns True if successful, False if the archive doesn't exist yet.
    """
    try:
        gcs = _get_gcs_client()
        bucket = gcs.bucket(bucket_name)
        blob = bucket.blob(GCS_MODEL_OBJECT)

        if not blob.exists():
            logger.info("No GCS model cache found — will download from HuggingFace")
            return False

        logger.info(f"Restoring models from GCS: gs://{bucket_name}/{GCS_MODEL_OBJECT}")
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
            tmp_path = tmp.name

        blob.download_to_filename(tmp_path)
        logger.info("Download complete, unpacking...")

        SURYA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with tarfile.open(tmp_path, "r:gz") as tar:
            tar.extractall(str(SURYA_CACHE_DIR.parent))

        os.unlink(tmp_path)
        logger.info("Models restored from GCS cache")
        return True

    except Exception as e:
        logger.warning(f"GCS restore failed (will fall back to HuggingFace): {e}")
        return False


def save_to_gcs(bucket_name: str) -> None:
    """
    Pack the Surya model directory and upload to GCS.
    Called after a successful HuggingFace download so future
    cold starts can use the GCS cache instead.
    """
    if not SURYA_CACHE_DIR.exists():
        logger.warning("Surya cache dir not found, skipping GCS save")
        return

    try:
        logger.info("Packing models for GCS upload...")
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
            tmp_path = tmp.name

        with tarfile.open(tmp_path, "w:gz") as tar:
            tar.add(str(SURYA_CACHE_DIR), arcname="datalab/models")

        size_mb = os.path.getsize(tmp_path) / 1024 / 1024
        logger.info(f"Uploading {size_mb:.0f} MB to gs://{bucket_name}/{GCS_MODEL_OBJECT}")

        gcs = _get_gcs_client()
        bucket = gcs.bucket(bucket_name)
        blob = bucket.blob(GCS_MODEL_OBJECT)
        blob.upload_from_filename(tmp_path)
        os.unlink(tmp_path)
        logger.info("Models saved to GCS cache")

    except Exception as e:
        logger.warning(f"GCS save failed (non-fatal): {e}")
