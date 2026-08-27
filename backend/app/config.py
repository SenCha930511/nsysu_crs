"""Application settings, parsed once from the environment / .env at the boundary."""

from datetime import date
from typing import Final

from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_DATABASE_URL: Final = "postgresql://postgres:postgres@postgres:5432/nsysu_crs"
_DEV_REDIS_URL: Final = "redis://redis:6379/0"


class Settings(BaseSettings):
    """Env-driven settings. Keys mirror .env.example exactly.

    Mutable by design: pydantic-settings populates fields from env vars at
    construction; tests override fields via constructor kwargs.
    """

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Secrets / connection targets. .env overrides these; the dev defaults
    # point at the compose service names so a fresh clone still boots.
    database_url: str = _DEV_DATABASE_URL
    redis_url: str = _DEV_REDIS_URL
    app_secret: str

    # Semester contract (todo 2+).
    semester_year_sem: str = "1151"
    semester_start_date: date = date(2026, 9, 1)
    semester_end_date: date = date(2027, 1, 16)

    # Catalog pipeline cadence (todo 6).
    catalog_cron_offpeak: str = "7 * * * *"
    catalog_cron_peak: str = "*/10 * * * *"
    catalog_peak_dates: str = ""

    # Feature flags (todo 14/15).
    feature_first_round_write: bool = False

    # Session / write-queue / auth limits (todos 8, 14, 15).
    selcrs_session_ttl_sliding: int = 1800
    selcrs_session_ttl_hard: int = 7200
    write_queue_dwell_max: int = 600
    confirm_token_ttl: int = 300
    csrf_token_ttl: int = 900
    login_fail_limit: int = 5
    login_lock_minutes: int = 15
    login_ip_hourly_limit: int = 30

    # Circuit breaker (todo 17).
    breaker_failure_threshold: int = 5
    breaker_recovery_after: int = 300

    # CORS allowlist (todo 17 hardening; raw comma-separated string for now).
    allowed_origins: str = "http://localhost,http://localhost:8000,http://localhost:5173"

    tz: str = "Asia/Taipei"
