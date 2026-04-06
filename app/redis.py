"""Shared Redis client — one connection pool per process.

Used by the healthcheck and any future code that needs Redis outside of
Celery's own broker connection. Kept separate from celery_app.py so
importing it from web code doesn't drag Celery into the import graph.
"""

from functools import lru_cache

import redis

from config import settings


@lru_cache
def get_redis() -> redis.Redis:
    return redis.from_url(settings.redis_url, decode_responses=True)
