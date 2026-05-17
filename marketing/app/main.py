"""Marketing Analyzer — milestone 2 skeleton.

Real implementation lands in Phase 1 (see MARKETING_ANALYZER_PLAN.md).
For now this is a hello-world placeholder so the deploy bundles can
boot end-to-end and the build pipeline has something to build.
"""

import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from core.db import get_supabase
from core.logging import configure_logging
from core.observability import init_sentry
from core.redis import get_redis

configure_logging()
init_sentry()
logger = logging.getLogger(__name__)

app = FastAPI(title="Marketing Analyzer", version="0.0.1")


@app.get("/health")
async def liveness() -> dict:
    return {"status": "ok"}


@app.get("/health/ready")
async def readiness():
    """Same shape as salesagent's readiness check so monitoring is uniform."""
    checks: dict[str, str] = {}
    ok = True

    try:
        get_supabase().table("reps").select("id").limit(1).execute()
        checks["supabase"] = "ok"
    except Exception as exc:
        checks["supabase"] = f"fail: {exc.__class__.__name__}"
        ok = False
        logger.warning("Readiness: supabase check failed: %s", exc)

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


@app.get("/")
async def root() -> dict:
    return {
        "product": "marketing-analyzer",
        "status": "skeleton — Phase 1 implementation pending",
        "docs": "/docs",
    }
