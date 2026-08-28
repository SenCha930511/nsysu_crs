"""Sliding-log lockout semantics (plan todo 8; QA qa/08-lockout.log).

Pins: per-failure 15-min individual expiry; >=5 unexpired -> fixed 15-min
lock; the lock write is NX (never extends); expired entries decay one by one
so a post-lock window comes back clean (attacker must re-accumulate); IP
window is the fixed CLOCK hour, not a TTL.
"""

import pytest

from app.auth.lockout import (
    LOCKOUT_DAILY_TTL_SECONDS,
    LOCKOUT_TOTAL_KEY,
    FailureLog,
    IpLimiter,
    lockout_daily_key,
)
from tests.fake_redis import FakeRedis

WINDOW = 15 * 60


class Clock:
    def __init__(self, start: float = 1_800_000_000.0) -> None:
        self.moment = start

    def __call__(self) -> float:
        return self.moment

    def advance(self, seconds: float) -> None:
        self.moment += seconds


def _log(redis: FakeRedis, clock: Clock, limit: int = 5) -> FailureLog:
    return FailureLog(redis, fail_limit=limit, lock_minutes=15, now=clock)


@pytest.mark.anyio
async def test_failures_expire_individually():
    clock, redis = Clock(), FakeRedis()
    log = _log(redis, clock)
    redis._now = clock  # shared clock so fake TTL math follows the same time

    await log.record_credential_fail("M001")
    clock.advance(600)
    await log.record_credential_fail("M001")
    assert await log.unexpired_failures("M001") == 2

    clock.advance(WINDOW - 600 + 1)  # first failure's own 15 min just lapsed
    assert await log.unexpired_failures("M001") == 1


@pytest.mark.anyio
async def test_fifth_failure_locks_and_lock_is_fixed_and_unextending():
    clock, redis = Clock(), FakeRedis()
    redis._now = clock
    log = _log(redis, clock)

    results = [await log.record_credential_fail("M002") for _ in range(5)]
    assert results == [False, False, False, False, True]
    assert await log.is_locked("M002")
    assert redis.remaining_ttl("loginlock:M002") == WINDOW

    # Even a record call racing in later (NX semantics) must not extend it.
    clock.advance(300)
    await log.record_credential_fail("M002")
    assert redis.remaining_ttl("loginlock:M002") == WINDOW - 300

    clock.advance(WINDOW - 300 + 1)
    assert await log.is_locked("M002") is False


@pytest.mark.anyio
async def test_window_returns_clean_after_lock_expires():
    clock, redis = Clock(), FakeRedis()
    redis._now = clock
    log = _log(redis, clock)

    for _ in range(5):
        await log.record_credential_fail("M003")
    clock.advance(WINDOW + 1)
    assert await log.unexpired_failures("M003") == 0  # re-accumulate from zero
    assert await log.record_credential_fail("M003") is False  # 1st of a NEW budget


@pytest.mark.anyio
async def test_lock_is_scoped_per_student():
    redis = FakeRedis()
    log = _log(redis, Clock())
    for _ in range(5):
        await log.record_credential_fail("M004")
    assert await log.is_locked("M004")
    assert await log.is_locked("M005") is False


@pytest.mark.anyio
async def test_new_locks_increment_the_abuse_monitor_counters():
    clock, redis = Clock(), FakeRedis()
    redis._now = clock
    log = _log(redis, clock)
    daily = lockout_daily_key(clock.moment, "Asia/Taipei")

    # Given the first fixed lock trigger
    for _ in range(5):
        await log.record_credential_fail("M123")
    # Then the abuse monitor counters moved exactly once
    assert redis.peek(LOCKOUT_TOTAL_KEY) == "1"
    assert redis.peek(daily) == "1"
    assert redis.remaining_ttl(daily) == LOCKOUT_DAILY_TTL_SECONDS

    # When a racing record lands while the lock still stands (NX did not create)
    clock.advance(300)
    await log.record_credential_fail("M123")
    # Then nothing double-counts
    assert redis.peek(LOCKOUT_TOTAL_KEY) == "1"

    # And when the lock and the failure window both decay, the next real trigger counts again
    clock.advance(WINDOW - 300 + 1)
    for _ in range(5):
        await log.record_credential_fail("M123")
    assert redis.peek(LOCKOUT_TOTAL_KEY) == "2"
    assert redis.peek(daily) == "2"


@pytest.mark.anyio
async def test_ip_window_is_the_fixed_clock_hour():
    clock, redis = Clock(), FakeRedis()
    redis._now = clock
    limiter = IpLimiter(redis, hourly_limit=2, now=clock)

    assert [await limiter.hit("1.2.3.4"), await limiter.hit("1.2.3.4")] == [1, 2]
    third = await limiter.hit("1.2.3.4")
    assert third == 3 and not limiter.admits(third)  # inclusive count, reject

    # A TTL later but the SAME clock hour: still the same bucket.
    clock.advance(3599 - (clock.moment % 3600) + 1)  # cross into the next hour
    assert await limiter.hit("1.2.3.4") == 1


@pytest.mark.anyio
async def test_ip_buckets_are_per_ip():
    redis = FakeRedis()
    limiter = IpLimiter(redis, hourly_limit=30)
    for _ in range(30):
        await limiter.hit("10.0.0.1")
    assert await limiter.hit("10.0.0.2") == 1
