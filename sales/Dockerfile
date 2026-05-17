# Sales Call Analyzer image.
# Build context = repo root (monorepo). Invoke with:
#   docker build -f sales/Dockerfile -t gogrowlabs/sales:latest .

# ── Stage 1: builder ─────────────────────────────────────────
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# System deps needed only for wheel builds
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Per-product requirements: shared deps + sales-specific deps.
COPY requirements/shared.txt requirements/sales.txt /build/
RUN pip install --prefix=/install -r shared.txt -r sales.txt


# ── Stage 2: runtime ─────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/usr/local/bin:$PATH"

# Non-root user
RUN groupadd --system app && useradd --system --gid app --home /app app

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Only sales + shared core land in the runtime image. No marketing/ on disk —
# this enforces the per-product license boundary (sales-only clients can audit
# that no marketing code is shipped to their VPS).
COPY --chown=app:app core /app/core
COPY --chown=app:app sales /app/sales

USER app

EXPOSE 8000

# Default command is overridden by docker-compose per service (api/worker/beat)
CMD ["uvicorn", "sales.app.main:app", "--host", "0.0.0.0", "--port", "8000"]

# Healthcheck — hits the /health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; \
        sys.exit(0) if urllib.request.urlopen('http://localhost:8000/health').status == 200 else sys.exit(1)" \
        || exit 1
