"""Celery application — broker and basic config."""

from celery import Celery
from config import settings

celery_app = Celery(
    "sales_agent",
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
    # Auto-discover tasks inside app.workers
    imports=["app.workers.tasks"],
)
