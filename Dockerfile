# ── Build stage ─────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir --prefix=/install --no-deps .

# ── Runtime stage ───────────────────────────────────────────
FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

WORKDIR /app

COPY static/ static/
COPY templates/ templates/

# Non-root user for security
RUN useradd -m -r counselai && \
    mkdir -p /app/data && \
    chown -R counselai:counselai /app
USER counselai

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/health')" || exit 1

CMD ["python", "-m", "gunicorn", "counselai.api.app:app", \
     "-k", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8501", \
     "--workers", "2", \
     "--timeout", "120", \
     "--graceful-timeout", "30"]
