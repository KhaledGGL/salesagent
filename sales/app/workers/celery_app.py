"""Celery application — broker, worker config, and beat schedule."""

from celery import Celery
from celery.schedules import crontab

from core.observability import init_sentry
from core.config import settings

# Initialize Sentry at module load so both the worker and beat processes
# capture errors from the very first task dispatch.
init_sentry()

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
    imports=["sales.app.workers.tasks"],
)


# ── Beat schedule ────────────────────────────────────────────────────────────
# cron day-of-week: 0/7=Sunday, 1=Monday, ..., 6=Saturday
_DAY_OF_WEEK_MAP = {
    "sunday": 0,
    "monday": 1,
    "tuesday": 2,
    "wednesday": 3,
    "thursday": 4,
    "friday": 5,
    "saturday": 6,
}


def _day_to_cron(name: str) -> int:
    """Translate 'monday' → 1, default to Monday on unknown input."""
    return _DAY_OF_WEEK_MAP.get((name or "monday").lower(), 1)


celery_app.conf.beat_schedule = {
    "weekly-sales-report": {
        "task": "generate_weekly_report",
        "schedule": crontab(
            hour=settings.weekly_report_hour,
            minute=0,
            day_of_week=_day_to_cron(settings.weekly_report_day),
        ),
    },
    "weekly-coaching-lesson": {
        "task": "generate_coaching_lesson",
        "schedule": crontab(
            hour=settings.weekly_report_hour,
            minute=5,
            day_of_week=_day_to_cron(settings.weekly_report_day),
        ),
    },
    "weekly-marketing-intel": {
        "task": "generate_marketing_intel",
        "schedule": crontab(
            hour=settings.weekly_report_hour,
            minute=10,
            day_of_week=_day_to_cron(settings.weekly_report_day),
        ),
    },
}
