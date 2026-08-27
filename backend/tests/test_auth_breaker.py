"""School breaker state machine (plan todo 8; QA qa/08-unknown.log).

Pins: 5th consecutive UNKNOWN opens; while open admit() is False (the router
serves a LOCAL 503 - no school call, no streak feedback); after
recovery_after a single probe is admitted per gate; a coherent answer closes
everything; another UNKNOWN re-stamps the open instant.
"""

import pytest

from app.auth.breaker import SchoolBreaker

from tests.fake_redis import FakeRedis


class Clock:
    def __init__(self, start: float = 1_800_000_000.0) -> None:
        self.moment = start

    def __call__(self) -> float:
        return self.moment

    def advance(self, seconds: float) -> None:
        self.moment += seconds


@pytest.mark.anyio
async def test_five_unknowns_open_the_breaker_and_local_503s_do_not_feedback():
    clock, redis = Clock(), FakeRedis()
    redis._now = clock
    breaker = SchoolBreaker(redis, failure_threshold=5, recovery_after=300, now=clock)

    for expected_streak in range(1, 5):
        assert await breaker.record_unknown() == expected_streak
        assert await breaker.admit() is True  # still closed below threshold

    assert await breaker.record_unknown() == 5
    for _ in range(3):
        assert await breaker.admit() is False  # local 503s, zero feedback
    assert await redis.get("breaker:school:streak") == "5"  # unchanged


@pytest.mark.anyio
async def test_recovery_admits_one_probe_and_coherent_answer_closes():
    clock, redis = Clock(), FakeRedis()
    redis._now = clock
    breaker = SchoolBreaker(redis, failure_threshold=5, recovery_after=300, now=clock)

    for _ in range(5):
        await breaker.record_unknown()
    clock.advance(299)
    assert await breaker.admit() is False
    clock.advance(1)
    assert await breaker.admit() is True  # the probe
    assert await breaker.admit() is False  # gate: one per minute

    await breaker.record_classified()  # any coherent school answer
    assert await redis.get("breaker:school:streak") is None
    assert await redis.get("breaker:school:opened_at") is None
    assert await breaker.admit() is True


@pytest.mark.anyio
async def test_failed_probe_restamps_the_open_instant():
    clock, redis = Clock(), FakeRedis()
    redis._now = clock
    breaker = SchoolBreaker(redis, failure_threshold=5, recovery_after=300, now=clock)

    for _ in range(5):
        await breaker.record_unknown()
    clock.advance(300)
    assert await breaker.admit() is True  # probe
    await breaker.record_unknown()  # probe failed: wait restarts from NOW
    clock.advance(299)
    assert await breaker.admit() is False
    clock.advance(1)
    assert await breaker.admit() is True


@pytest.mark.anyio
async def test_coherent_answer_mid_streak_resets_the_count():
    clock, redis = Clock(), FakeRedis()
    redis._now = clock
    breaker = SchoolBreaker(redis, failure_threshold=5, recovery_after=300, now=clock)

    for _ in range(4):
        await breaker.record_unknown()
    await breaker.record_classified()
    for _ in range(4):
        await breaker.record_unknown()
    assert await breaker.admit() is True  # 4 of a NEW streak, still closed
    assert await breaker.record_unknown() == 5
    assert await breaker.admit() is False
