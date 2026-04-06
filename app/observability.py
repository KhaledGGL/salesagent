"""Sentry initialization — shared across FastAPI and Celery entrypoints.

Guarded on SENTRY_DSN so local/dev runs without Sentry set up are a no-op.
Call init_sentry() exactly once per process before any request handling.
"""

import logging

from config import settings

logger = logging.getLogger(__name__)

_initialized = False


def init_sentry() -> None:
    """Initialize Sentry if SENTRY_DSN is configured.

    Uses auto-detection for FastAPI and Celery integrations — sentry-sdk
    2.x picks them up automatically when the frameworks are already
    imported at init time. Explicit integration lists are only needed
    to customize behavior, which we don't.
    """
    global _initialized
    if _initialized:
        return

    if not settings.sentry_dsn:
        logger.info("Sentry disabled (no SENTRY_DSN configured)")
        _initialized = True
        return

    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.app_env,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        profiles_sample_rate=settings.sentry_profiles_sample_rate,
        # Attach request bodies (webhook payloads) to errors — critical for
        # debugging "why did this webhook fail?" incidents. Redacted by
        # Sentry's default PII scrubbing for things like auth headers.
        send_default_pii=False,
        attach_stacktrace=True,
    )
    _initialized = True
    logger.info("Sentry initialized: env=%s", settings.app_env)
