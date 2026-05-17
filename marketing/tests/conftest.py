"""Shared test setup for marketing tests.

Sets required env vars before any marketing/core module imports so
pydantic-settings doesn't blow up during test collection. Mirrors
sales/tests/conftest.py — keep the two in sync if env contract changes.
"""

import os

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("WEBHOOK_SECRET", "test-webhook-secret")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-key")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("GHL_API_KEY", "test-ghl-key")
os.environ.setdefault("GHL_LOCATION_ID", "test-location")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("SLACK_BOT_TOKEN", "xoxb-test")
os.environ.setdefault("SLACK_SCORECARD_CHANNEL", "test-scorecards")
os.environ.setdefault("SLACK_REPORTS_CHANNEL", "test-reports")

# Force cached settings to reload with the env we just set
from core.config import get_settings  # noqa: E402

get_settings.cache_clear()
