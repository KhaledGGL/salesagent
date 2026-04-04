"""FastAPI application entrypoint."""

import logging

from fastapi import FastAPI

from app.webhooks.ghl import router as ghl_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

app = FastAPI(title="Sales Call Analyzer", version="0.1.0")

# ── Routers ──────────────────────────────────────────────────────────────────
app.include_router(ghl_router)


# ── Health check ─────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok"}
