# ── Marker PDF → Markdown conversion service ────────────────────────────────
FROM python:3.11-slim

# System libraries required by Surya (image processing, PDF rendering)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        libsm6 \
        libxext6 \
        libxrender-dev \
        poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Install CPU-only PyTorch first ─────────────────────────────────────────
# The default PyPI torch includes CUDA binaries (~2 GB download).
# The CPU-only build is ~200 MB — same functionality, no GPU needed.
# pip won't re-download torch when marker-pdf is installed next because
# the already-installed version satisfies marker's version constraint.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# ── Install remaining dependencies ────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Application code ─────────────────────────────────────────────────────────
COPY . .

# Model cache at runtime (ephemeral, re-downloaded on cold start)
ENV HF_HOME=/app/models
ENV TORCH_HOME=/app/models/torch
ENV TRANSFORMERS_CACHE=/app/models/transformers

ENV PORT=8080
EXPOSE 8080

CMD ["python", "app.py"]
