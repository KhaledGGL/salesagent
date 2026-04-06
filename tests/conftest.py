"""Shared test setup.

Sets required env vars before any app module imports so pydantic-settings
doesn't blow up during test collection. Keep this file import-order-sensitive.
"""

import os

# ── Fake env — must be set BEFORE importing config/app modules ───────────────
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
from config import get_settings  # noqa: E402

get_settings.cache_clear()


# ── Shared fixtures ──────────────────────────────────────────────────────────

import pytest  # noqa: E402


@pytest.fixture
def sample_scorecard_json() -> dict:
    """A valid ScorecardOutput shape — mirrors what Claude should return."""
    return {
        "scores": {
            "rapport": 7,
            "diagnosis": 8,
            "objection_handling": 6,
            "close": 7,
            "compliance": 9,
            "overall": 7,
        },
        "therapist_mode_flag": False,
        "therapist_mode_reason": None,
        "ai_summary": "Solid discovery, weak close. Work on closing timing.",
        "win_loss_moment": {
            "timestamp_seconds": 645,
            "description": "Prospect opened up about budget concerns after NEPQ consequence question.",
        },
        "coaching_moments": [
            {
                "timestamp_seconds": 320,
                "category": "diagnosis",
                "severity": "medium",
                "note": "Missed opportunity to ask about prior solutions tried.",
            },
        ],
        "objections": [
            {
                "timestamp_seconds": 890,
                "objection_type": "price",
                "objection_text": "That's more than we were expecting.",
                "handling_quality": "good",
            },
        ],
    }
