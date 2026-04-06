"""FastAPI application entrypoint."""

from fastapi import FastAPI

from app.logging import configure_logging
from app.webhooks.ghl import router as ghl_router

configure_logging()

app = FastAPI(title="Sales Call Analyzer", version="0.1.0")

# ── Routers ──────────────────────────────────────────────────────────────────
app.include_router(ghl_router)


# ── Health check ─────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok"}
