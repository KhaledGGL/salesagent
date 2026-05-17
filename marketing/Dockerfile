# Marketing Analyzer image.
# Build context = repo root (monorepo). Invoke with:
#   docker build -f marketing/Dockerfile -t gogrowlabs/marketing:latest .

# ── Stage 1: builder ─────────────────────────────────────────
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# Per-product requirements: shared deps + marketing-specific deps.
COPY requirements/shared.txt requirements/marketing.txt /build/
RUN pip install --prefix=/install -r shared.txt -r marketing.txt


# ── Stage 2: runtime ─────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/usr/local/bin:$PATH"

RUN groupadd --system app && useradd --system --gid app --home /app app

WORKDIR /app

COPY --from=builder /install /usr/local

# Only marketing + shared core land in the runtime image. No sales/ on disk —
# enforces the per-product license boundary.
COPY --chown=app:app core /app/core
COPY --chown=app:app marketing /app/marketing

USER app

EXPOSE 8001

CMD ["uvicorn", "marketing.app.main:app", "--host", "0.0.0.0", "--port", "8001"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; \
        sys.exit(0) if urllib.request.urlopen('http://localhost:8001/health').status == 200 else sys.exit(1)" \
        || exit 1
