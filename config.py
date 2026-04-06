from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # App
    app_env: str = "development"
    secret_key: str
    webhook_secret: str

    # Supabase
    supabase_url: str
    supabase_service_key: str

    # Redis / Celery
    redis_url: str = "redis://redis:6379/0"

    # GHL
    ghl_api_key: str
    ghl_location_id: str

    # Anthropic
    anthropic_api_key: str

    # Slack
    slack_bot_token: str
    slack_scorecard_channel: str = "sales-scorecards"
    slack_reports_channel: str = "sales-reports"

    # Celery beat
    weekly_report_day: str = "monday"
    weekly_report_hour: int = 8

    # Observability (optional — empty DSN disables Sentry cleanly)
    sentry_dsn: str | None = None
    sentry_traces_sample_rate: float = 0.1
    sentry_profiles_sample_rate: float = 0.0

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
