"""Runtime current-semester resolution - replaces the SEMESTER_YEAR_SEM hardcode.

Precedence: explicit env override > Redis-cached discovery (6h) > live
discovery from the school's own YRSM page > None (callers degrade; the site
refuses to guess a semester). The 6h cache window is the deliberate rollover
tradeoff: at semester switch the cached prior code can serve at most ~6h
stale (bounded, logged-visible via the discovery path) instead of pinning
the whole site to a stale literal for an entire semester.
"""

from typing import Final

from app.auth.redis_iface import AuthRedis
from app.catalog.discover import DiscoveryError, discover_current_d0
from app.config import Settings
from app.selcrs.errors import SelcrsError

SEMESTER_CACHE_KEY: Final = "semester:current"
SEMESTER_CACHE_TTL_SECONDS: Final = 6 * 3600


async def resolve_year_sem(redis: AuthRedis, settings: Settings) -> str | None:
    """Current year-semester code (e.g. "1152"), or None when nothing
    trustworthy is available: no override, empty cache, and live discovery
    failed. Discovery errors never reach callers - they see None and degrade.
    """
    if settings.semester_year_sem:
        return settings.semester_year_sem
    cached = await redis.get(SEMESTER_CACHE_KEY)
    if cached is not None:
        return cached
    try:
        d0 = await discover_current_d0()
    except (DiscoveryError, SelcrsError):
        return None
    await redis.set(SEMESTER_CACHE_KEY, d0, ex=SEMESTER_CACHE_TTL_SECONDS)
    return d0
