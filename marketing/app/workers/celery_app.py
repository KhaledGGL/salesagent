"""Marketing Analyzer Celery app — skeleton.

Phase 1 will register real tasks here (ad API pull, identity stitching,
report generation). For now this exists so the deploy bundles' worker
and beat containers can boot without import errors.
"""

from celery import Celery

from core.config import settings
from core.observability import init_sentry

init_sentry()

celery_app = Celery(
    "marketing_analyzer",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_queue="marketing",
    # Phase 1: add `imports=["marketing.app.workers.tasks"]` once tasks exist.
)
