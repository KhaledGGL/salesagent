"""FastAPI application entrypoint."""

import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.db import get_supabase
from app.logging import configure_logging
from app.observability import init_sentry
from app.redis import get_redis
from app.ui.routes import router as ui_router
from app.webhooks.ghl import router as ghl_router

configure_logging()
init_sentry()
logger = logging.getLogger(__name__)

app = FastAPI(title="Sales Call Analyzer", version="0.1.0")

# ── Routers ──────────────────────────────────────────────────────────────────
app.include_router(ghl_router)
app.include_router(ui_router)


# ── Liveness: process is alive. Used by Docker HEALTHCHECK and load balancers
# for fast "is this container dead?" checks. Must be cheap and never touch
# external dependencies.
@app.get("/health")
async def liveness() -> dict:
    return {"status": "ok"}


# ── Readiness: dependencies are reachable. Used by orchestrators (k8s, ECS,
# Fly) to decide whether to route traffic to this instance. Returning 503
# makes the orchestrator keep the pod alive but pull it out of the load
# balancer rotation until deps recover.
@app.get("/health/ready")
async def readiness():
    checks: dict[str, str] = {}
    ok = True

    # Supabase — cheap round-trip against a small table
    try:
        get_supabase().table("reps").select("id").limit(1).execute()
        checks["supabase"] = "ok"
    except Exception as exc:
        checks["supabase"] = f"fail: {exc.__class__.__name__}"
        ok = False
        logger.warning("Readiness: supabase check failed: %s", exc)

    # Redis — PING is the canonical liveness op
    try:
        get_redis().ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"fail: {exc.__class__.__name__}"
        ok = False
        logger.warning("Readiness: redis check failed: %s", exc)

    if not ok:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "checks": checks},
        )
    return {"status": "ready", "checks": checks}
