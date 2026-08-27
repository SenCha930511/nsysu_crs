"""Catalog ingest scheduler (plan todo 6).

Cadence: two cron expressions from env - ``CATALOG_CRON_OFFPEAK`` (weekday /
ordinary days) and ``CATALOG_CRON_PEAK`` (selection-window days), with
``CATALOG_PEAK_DATES`` (comma-separated ISO dates and ``A..B`` ranges,
inclusive, Asia/Taipei) gating which one applies on a given day. Today's
expression determines both the next fire time (via croniter) and the lock
TTL: ``SET ingest:lock <uuid> NX EX <2x interval>``.

Singleton / coalesce contract (plan): while one round holds the lock, new
ticks COALESCE (skip; nothing queues, never concurrent). Every tick releases
the lock via a Lua compare-and-del on its token, so an overran old round can
never delete a newer round's lock. If the process crashes mid-round the key
simply expires at EX - at most ceil(EX/interval)-1 ticks are skipped (peak:
1, off-peak: 1), a documented, accepted degradation.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final, Protocol
from zoneinfo import ZoneInfo

import anyio
from croniter import croniter

from app.config import Settings

LOCK_KEY: Final = "ingest:lock"
#: Floor for EX even if a pathological cron fires seconds apart.
_MIN_LOCK_TTL_SECONDS: Final = 60

_RELEASE_LUA: Final = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


class RedisLockClient(Protocol):
    """The redis.asyncio subset the lock needs (tests substitute a fake)."""

    async def set(
        self, name: str, value: str, *, nx: bool = False, ex: int | None = None
    ) -> object: ...

    async def eval(self, script: str, numkeys: int, *args: object) -> object: ...


def parse_peak_date_ranges(spec: str) -> tuple[tuple[date, date], ...]:
    """Parse ``CATALOG_PEAK_DATES``: ISO dates and inclusive ``A..B`` ranges,
    comma-separated. Empty spec -> no peak days (off-peak cadence always)."""
    ranges: list[tuple[date, date]] = []
    for chunk in (piece.strip() for piece in spec.split(",")):
        if not chunk:
            continue
        start_text, separator, end_text = chunk.partition("..")
        start = date.fromisoformat(start_text.strip())
        end = date.fromisoformat(end_text.strip()) if separator else start
        if end < start:
            raise ValueError(f"peak date range end before start: {chunk!r}")
        ranges.append((start, end))
    return tuple(ranges)


def is_peak_day(day: date, ranges: tuple[tuple[date, date], ...]) -> bool:
    """True iff ``day`` falls inside any configured peak range (inclusive)."""
    return any(start <= day <= end for start, end in ranges)


@dataclass(frozen=True, slots=True)
class CronPolicy:
    """One cron expression: next fire + the fire-to-fire interval (for EX)."""

    expression: str

    def next_after(self, moment: datetime) -> datetime:
        """First fire strictly after ``moment`` (aware, same tz as input)."""
        return croniter(self.expression, moment).get_next(datetime)

    def interval_seconds(self, moment: datetime) -> int:
        """Seconds between the next two fires after ``moment``."""
        first = self.next_after(moment)
        second = self.next_after(first)
        return max(int((second - first).total_seconds()), 1)


class IngestLock:
    """Redis singleton lock with token-checked release (see module doc)."""

    def __init__(self, redis: RedisLockClient) -> None:
        self._redis: Final = redis
        self.token: str | None = None

    async def acquire(self, ttl_seconds: int) -> str | None:
        """Try to take the lock; returns the token, or None when coalesced."""
        token = uuid.uuid4().hex
        taken = await self._redis.set(
            LOCK_KEY,
            token,
            nx=True,
            ex=max(ttl_seconds, _MIN_LOCK_TTL_SECONDS),
        )
        if not taken:
            return None
        self.token = token
        return token

    async def release(self, token: str) -> bool:
        """Lua compare-and-del: only delete when WE still hold the token."""
        released = await self._redis.eval(_RELEASE_LUA, 1, LOCK_KEY, token)
        if self.token == token:
            self.token = None
        return bool(released)


async def scheduler_loop(
    settings: Settings,
    *,
    redis: RedisLockClient,
    run_once: Callable[[], Awaitable[object]],
    sleep: Callable[[float], Awaitable[None]] = anyio.sleep,
    now: Callable[[], datetime] | None = None,
    peak_ranges: tuple[tuple[date, date], ...] | None = None,
    lock_factory: Callable[[RedisLockClient], IngestLock] = IngestLock,
    log: Callable[[str], None] | None = None,
) -> None:
    """Tick forever: fire the active cron, coalesce when locked, else ingest.

    Injectable clock/sleep/lock/log seams keep tests instant and offline; the
    worker passes the real implementations.
    """
    tz = ZoneInfo(settings.tz)
    now_fn = now if now is not None else lambda: datetime.now(tz)
    ranges = (
        peak_ranges
        if peak_ranges is not None
        else parse_peak_date_ranges(settings.catalog_peak_dates)
    )
    emit = log if log is not None else (lambda message: None)

    while True:
        moment = now_fn()
        peak = is_peak_day(moment.date(), ranges)
        expression = settings.catalog_cron_peak if peak else settings.catalog_cron_offpeak
        policy = CronPolicy(expression)
        wake = policy.next_after(moment)
        ttl = 2 * policy.interval_seconds(moment)
        await sleep(max((wake - moment).total_seconds(), 0.0))

        lock = lock_factory(redis)
        token = await lock.acquire(ttl)
        if token is None:
            emit(f"catalog ingest tick coalesced (lock held; cron={expression!r})")
            continue
        try:
            emit(f"catalog ingest start (cron={expression!r}, peak={peak})")
            report = await run_once()
            emit(f"catalog ingest done: {report!r}")
        finally:
            await lock.release(token)
