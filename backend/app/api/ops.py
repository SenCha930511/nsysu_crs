"""GET /api/ops/state (plan todo 17): breaker posture + abuse counters.

Two trust levels on ONE route:

- PUBLIC (any client): only coarse posture - ``breaker.state``
  (closed/open/half-open) and ``mode`` (normal/read-only). This is what the
  SPA's global banner polls; it reveals nothing an attacker couldn't already
  infer by calling /api/auth/login once.
- ADMIN: the full detail (streak, opened_at, thresholds, lockout counters).
  Gate = ``X-App-Secret`` header equal to APP_SECRET (constant-time compare)
  OR a direct connection from loopback (no reverse proxy in between - Caddy
  makes the peer its own container IP, so through-Caddy access needs the
  header). Documented in docs/runbook.md.

Never calls ``SchoolBreaker.admit()``: reporting must not consume the
half-open probe gate (admit has side effects).
"""

import hmac
import time
from datetime import datetime, timedelta
from typing import Annotated, Final, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from app.api.deps import get_redis
from app.auth.breaker import OPENED_AT_KEY, PROBE_GATE_SECONDS, STREAK_KEY
from app.auth.lockout import LOCKOUT_TOTAL_KEY, lockout_daily_key
from app.auth.redis_iface import AuthRedis
from app.config import Settings

router: Final = APIRouter()

ADMIN_HEADER: Final = "X-App-Secret"

# PEP 695 type aliases (mypy rejects a Final VALUE used as an annotation).
type _BreakerState = Literal["closed", "open", "half-open"]
type _Mode = Literal["normal", "read-only"]


class BreakerStateOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    state: _BreakerState
    mode: _Mode
    streak: int | None
    opened_at: str | None
    failure_threshold: int | None
    recovery_after: int | None
    probe_gate_seconds: int | None


class LockoutOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    today: int
    yesterday: int
    total: int


class OpsStateOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    breaker: BreakerStateOut
    lockouts: LockoutOut | None


def is_admin(request: Request, settings: Settings) -> bool:
    """X-App-Secret header match, or a direct (unproxied) loopback client."""
    provided = request.headers.get(ADMIN_HEADER)
    if provided is not None and hmac.compare_digest(provided, settings.app_secret):
        return True
    host = request.client.host if request.client is not None else ""
    return host in ("127.0.0.1", "::1", "localhost")


@router.get("/api/ops/state", response_model=OpsStateOut)
async def get_ops_state(
    request: Request, redis: Annotated[AuthRedis, Depends(get_redis)]
) -> OpsStateOut:
    settings: Settings = request.app.state.settings
    tz = ZoneInfo(settings.tz)
    now = time.time()

    opened_at_raw = await redis.get(OPENED_AT_KEY)
    if opened_at_raw is None:
        state: _BreakerState = "closed"
    elif now - float(opened_at_raw) < settings.breaker_recovery_after:
        state = "open"
    else:
        state = "half-open"

    admin = is_admin(request, settings)
    opened_at_iso = (
        datetime.fromtimestamp(float(opened_at_raw), tz).isoformat(timespec="seconds")
        if admin and opened_at_raw is not None
        else None
    )
    lockouts: LockoutOut | None = None
    if admin:
        today = lockout_daily_key(now, settings.tz)
        yesterday = lockout_daily_key(
            (datetime.fromtimestamp(now, tz) - timedelta(days=1)).timestamp(), settings.tz
        )
        lockouts = LockoutOut(
            today=int(await redis.get(today) or 0),
            yesterday=int(await redis.get(yesterday) or 0),
            total=int(await redis.get(LOCKOUT_TOTAL_KEY) or 0),
        )
    return OpsStateOut(
        breaker=BreakerStateOut(
            state=state,
            mode="normal" if state == "closed" else "read-only",
            streak=int(await redis.get(STREAK_KEY) or 0) if admin else None,
            opened_at=opened_at_iso,
            failure_threshold=settings.breaker_failure_threshold if admin else None,
            recovery_after=settings.breaker_recovery_after if admin else None,
            probe_gate_seconds=PROBE_GATE_SECONDS if admin else None,
        ),
        lockouts=lockouts,
    )
