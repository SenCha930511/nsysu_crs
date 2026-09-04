"""Redis last-good store for the parsed front-page schedule.

One JSON blob at ``schedule:selcrs:v1`` with NO expiry: a stale snapshot is
strictly better than none (the schedule moves once per semester), and
staleness is a *read-time* property decided from ``fetched_at`` by the API
layer, not by Redis TTL. A 30s refresh mutex coalesces concurrent misses;
school concurrency is still bounded by the adapter's process-wide semaphore
either way.
"""

import json
from typing import Final

from app.auth.redis_iface import AuthRedis

CACHE_KEY: Final = "schedule:selcrs:v1"
_REFRESH_LOCK_KEY: Final = "schedule:selcrs:refresh"
REFRESH_LOCK_TTL: Final = 30

#: A cached payload older than this triggers a foreground refresh.
FRESHNESS_SECONDS: Final = 6 * 3600


async def load_cached(redis: AuthRedis) -> dict[str, object] | None:
    raw = await redis.get(CACHE_KEY)
    if raw is None:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None  # corrupt blob: treat as absent, refresh will replace
    return payload if isinstance(payload, dict) else None


async def save_cached(redis: AuthRedis, payload: dict[str, object]) -> None:
    await redis.set(CACHE_KEY, json.dumps(payload, ensure_ascii=False))


async def acquire_refresh_lock(redis: AuthRedis) -> bool:
    """True iff THIS caller runs the school fetch; others serve stale."""
    return bool(await redis.set(_REFRESH_LOCK_KEY, "1", nx=True, ex=REFRESH_LOCK_TTL))


async def release_refresh_lock(redis: AuthRedis) -> None:
    await redis.delete(_REFRESH_LOCK_KEY)
