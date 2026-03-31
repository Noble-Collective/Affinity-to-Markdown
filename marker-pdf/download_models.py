#!/usr/bin/env python3
"""
Run during Docker build to pre-download Marker/Surya models into the image.
This avoids cold-start model downloads at runtime on Cloud Run.
"""
import os
import sys

# Pin cache locations before importing anything that touches torch/HF
os.environ.setdefault("HF_HOME", "/app/models")
os.environ.setdefault("TORCH_HOME", "/app/models/torch")
os.environ.setdefault("TRANSFORMERS_CACHE", "/app/models/transformers")

import torch

print(f"PyTorch {torch.__version__}")
print(f"CUDA available: {torch.cuda.is_available()}")
print("Downloading Marker/Surya models (CPU mode) ...")

try:
    from marker.models import create_model_dict
    models = create_model_dict(device="cpu", dtype=torch.float32)
    print(f"\u2713 Downloaded {len(models)} model(s): {list(models.keys())}")
    del models
except Exception as e:
    print(f"ERROR downloading models: {e}", file=sys.stderr)
    sys.exit(1)

print("Model pre-download complete.")
