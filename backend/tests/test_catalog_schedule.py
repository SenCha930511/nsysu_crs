"""Scheduler tests: peak-date gating, cron math, Redis singleton lock (todo 6).

The lock tests run against an in-memory FakeRedis that mirrors the
SET-NX-EX + Lua compare-and-del semantics the real client provides; no TCP.
"""

import anyio

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.catalog.schedule import (
    LOCK_KEY,
    CronPolicy,
    IngestLock,
    is_peak_day,
    parse_peak_date_ranges,
    scheduler_loop,
)
from app.config import Settings

TZ = ZoneInfo("Asia/Taipei")


class FakeRedis:
    """In-memory stand-in for the redis.asyncio subset the lock uses."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.set_calls: list[tuple[str, str, bool, int | None]] = []

    async def set(self, name, value, *, nx=False, ex=None):
        self.set_calls.append((name, value, nx, ex))
        if nx and name in self.store:
            return None
        self.store[name] = value
        return True

    async def eval(self, script, numkeys, *args):
        key, token = args[0], args[1]
        if self.store.get(key) == token:
            del self.store[key]
            return 1
        return 0


class _StopLoop(Exception):
    """Test-only loop breaker raised from the fake sleeper."""


def _settings(**overrides) -> Settings:
    base = {
        "app_secret": "test-secret",
        "catalog_cron_offpeak": "7 * * * *",
        "catalog_cron_peak": "*/10 * * * *",
        "catalog_peak_dates": "",
    }
    base.update(overrides)
    return Settings(**base)


def test_peak_ranges_parse_dates_and_ranges():
    ranges = parse_peak_date_ranges("2026-08-28..2026-08-31, 2026-09-11")
    assert ranges == ((date(2026, 8, 28), date(2026, 8, 31)), (date(2026, 9, 11), date(2026, 9, 11)))
    assert parse_peak_date_ranges("") == ()
    with pytest.raises(ValueError):
        parse_peak_date_ranges("2026-09-01..2026-08-30")


def test_is_peak_day_inclusive_bounds():
    ranges = parse_peak_date_ranges("2026-08-28..2026-08-31")
    assert is_peak_day(date(2026, 8, 28), ranges)
    assert is_peak_day(date(2026, 8, 31), ranges)
    assert not is_peak_day(date(2026, 8, 27), ranges)
    assert not is_peak_day(date(2026, 9, 1), ranges)


def test_cron_policy_next_fire_and_interval():
    policy = CronPolicy("*/10 * * * *")
    moment = datetime(2026, 8, 28, 9, 3, 30, tzinfo=TZ)
    nxt = policy.next_after(moment)
    assert (nxt.hour, nxt.minute, nxt.second, nxt.tzinfo) == (9, 10, 0, TZ)
    assert policy.interval_seconds(moment) == 600
    hourly = CronPolicy("7 * * * *")
    assert hourly.interval_seconds(moment) == 3600


def test_lock_acquire_release_cycle():
    async def go():
        redis = FakeRedis()
        lock = IngestLock(redis)
        token = await lock.acquire(1200)
        assert token is not None
        # SET used NX + EX with the ttl passed through
        _, _, nx, ex = redis.set_calls[-1]
        assert nx and ex == 1200
        # coalesced competitor is refused
        competitor = IngestLock(redis)
        assert await competitor.acquire(1200) is None
        # wrong token must NOT delete (compare-and-del)
        assert await lock.release("not-the-token") is False
        assert LOCK_KEY in redis.store
        # right token deletes
        assert await lock.release(token) is True
        assert LOCK_KEY not in redis.store

    anyio.run(go)


def test_lock_ttl_floor_and_double_interval():
    async def go():
        redis = FakeRedis()
        lock = IngestLock(redis)
        await lock.acquire(10)  # below the 60s floor
        assert redis.set_calls[-1][3] == 60

    anyio.run(go)


def test_scheduler_runs_and_releases_on_peak_cron():
    calls = {"runs": 0, "log": []}

    async def run_once():
        calls["runs"] += 1
        return "report-ok"

    async def go():
        redis = FakeRedis()
        sleeps: list[float] = []
        ticks = iter([
            datetime(2026, 8, 28, 9, 0, 1, tzinfo=TZ),   # peak day (window)
            datetime(2026, 8, 28, 9, 10, 0, tzinfo=TZ),  # after first fire
        ])

        async def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)
            if len(sleeps) == 2:
                raise _StopLoop

        with pytest.raises(_StopLoop):
            await scheduler_loop(
                _settings(catalog_peak_dates="2026-08-28..2026-08-31"),
                redis=redis,
                run_once=run_once,
                sleep=fake_sleep,
                now=lambda: next(ticks),
                log=calls["log"].append,
            )
        assert calls["runs"] == 1
        # slept until the next */10 boundary (9:00:01 -> 9:10:00)
        assert sleeps[0] == pytest.approx(599.0)
        # peak cron + EX = 2x600s lock, released afterwards
        assert any("peak=True" in line for line in calls["log"])
        assert redis.set_calls[0][3] == 1200
        assert LOCK_KEY not in redis.store

    anyio.run(go)


def test_scheduler_coalesces_when_lock_held():
    calls = {"runs": 0, "log": []}

    async def run_once():
        calls["runs"] += 1

    async def go():
        redis = FakeRedis()
        redis.store[LOCK_KEY] = "someone-else"
        ticks = iter([
            datetime(2026, 8, 27, 10, 0, 1, tzinfo=TZ),  # before first tick
            datetime(2026, 8, 27, 11, 7, 0, tzinfo=TZ),  # at the skipped tick
        ])
        sleeps = 0

        async def fake_sleep(seconds: float) -> None:
            nonlocal sleeps
            sleeps += 1
            if sleeps == 2:
                raise _StopLoop

        with pytest.raises(_StopLoop):
            await scheduler_loop(
                _settings(),
                redis=redis,
                run_once=run_once,
                sleep=fake_sleep,
                now=lambda: next(ticks),
                log=calls["log"].append,
            )
        assert calls["runs"] == 0  # skipped, nothing queued
        assert any("coalesced" in line for line in calls["log"])
        assert redis.store[LOCK_KEY] == "someone-else"  # untouched

    anyio.run(go)
