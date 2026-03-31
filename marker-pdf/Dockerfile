# ── Marker PDF → Markdown conversion service ────────────────────────────────
# Bakes Surya/Marker models into the image at build time so Cloud Run
# instances start instantly without fetching ~3 GB of weights at runtime.

FROM python:3.11-slim

# System libraries required by Surya (image processing, PDF rendering)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        libsm6 \
        libxext6 \
        libxrender-dev \
        libgles2 \
        poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Python dependencies ──────────────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Pre-download Marker/Surya models ─────────────────────────────────────────
# Models are cached to /app/models so they are baked into the image layer.
# At runtime these env vars must match so the app finds them.
ENV HF_HOME=/app/models
ENV TORCH_HOME=/app/models/torch
ENV TRANSFORMERS_CACHE=/app/models/transformers

COPY download_models.py .
RUN python download_models.py

# ── Application code ─────────────────────────────────────────────────────────
COPY . .

ENV PORT=8080
EXPOSE 8080

CMD ["python", "app.py"]
