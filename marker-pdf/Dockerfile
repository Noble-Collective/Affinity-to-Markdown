# ── Marker PDF → Markdown conversion service ────────────────────────────────
# Models are NOT baked into the image (too large for Cloud Build timeout).
# Instead, models download to /app/models on first container startup and are
# then held in memory for the lifetime of the instance.

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

# ── Python dependencies ──────────────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Application code ─────────────────────────────────────────────────────────
COPY . .

# Model cache lives here at runtime (ephemeral, re-downloaded on cold start)
ENV HF_HOME=/app/models
ENV TORCH_HOME=/app/models/torch
ENV TRANSFORMERS_CACHE=/app/models/transformers

ENV PORT=8080
EXPOSE 8080

CMD ["python", "app.py"]
