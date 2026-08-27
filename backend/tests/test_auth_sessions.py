"""Site session + selcrs store TTL semantics (plan todo 8; QA qa/08-login-ok.log).

Pins: site session 7-day SLIDING (each resolve re-extends); logout drops the
site row AND both selcrs keys; selcrs jar = sliding 1800s freshness under a
hard 7200s cap that NX-anchors at login and wins over any amount of activity.
"""

import httpx
import pytest

from app.auth.sessions import (
    SITE_SESSION_TTL_SECONDS,
    create_site_session,
    delete_site_session,
    load_selcrs,
    resolve_site_session,
    store_selcrs,
)
from app.selcrs.jar import deserialize_cookies, serialize_cookies

from tests.fake_redis import FakeRedis

DAY = 24 * 3600


class Clock:
    def __init__(self, start: float = 1_800_000_000.0) -> None:
        self.moment = start

    def __call__(self) -> float:
        return self.moment

    def advance(self, seconds: float) -> None:
        self.moment += seconds


def _redis_with_clock() -> tuple[Clock, FakeRedis]:
    clock, redis = Clock(), FakeRedis()
    redis._now = clock
    return clock, redis


@pytest.mark.anyio
async def test_cookie_round_trip_canonical_order():
    jar = httpx.Cookies()
    jar.set("ASPSESSIONIDXXYZ", "BVALUE")
    jar.set("BIGipServerPL-Selcrs", "AVALUE")
    restored = deserialize_cookies(serialize_cookies(jar))
    assert restored.get("ASPSESSIONIDXXYZ") == "BVALUE"
    assert restored.get("BIGipServerPL-Selcrs") == "AVALUE"


@pytest.mark.anyio
async def test_site_session_is_sliding_seven_days():
    clock, redis = _redis_with_clock()
    sid = await create_site_session(redis, "M153000024")
    assert redis.remaining_ttl(f"site_session:{sid}") == SITE_SESSION_TTL_SECONDS

    clock.advance(6 * DAY)
    assert await resolve_site_session(redis, sid) == "M153000024"
    assert redis.remaining_ttl(f"site_session:{sid}") == SITE_SESSION_TTL_SECONDS

    clock.advance(7 * DAY + 1)  # no touch -> gone
    assert await resolve_site_session(redis, sid) is None


@pytest.mark.anyio
async def test_unknown_session_resolves_to_none():
    _, redis = _redis_with_clock()
    assert await resolve_site_session(redis, "nope") is None


@pytest.mark.anyio
async def test_logout_drops_site_session_and_both_selcrs_keys():
    _, redis = _redis_with_clock()
    sid = await create_site_session(redis, "M153000024")
    await store_selcrs(redis, sid, "[['a','b']]", sliding_ttl=1800, hard_ttl=7200)

    await delete_site_session(redis, sid)
    assert await resolve_site_session(redis, sid) is None
    assert await redis.get(f"selcrs:{sid}") is None
    assert await redis.get(f"selcrs_hard:{sid}") is None


@pytest.mark.anyio
async def test_selcrs_sliding_refreshes_but_hard_cap_wins():
    clock, redis = _redis_with_clock()
    sid = await create_site_session(redis, "M153000024")
    await store_selcrs(redis, sid, "[['a','b']]", sliding_ttl=1800, hard_ttl=7200)
    assert redis.remaining_ttl(f"selcrs:{sid}") == 1800
    assert redis.remaining_ttl(f"selcrs_hard:{sid}") == 7200

    clock.advance(1000)  # t=1000: alive; freshness slides to t=2800
    assert await load_selcrs(redis, sid, sliding_ttl=1800) == "[['a','b']]"
    assert redis.remaining_ttl(f"selcrs:{sid}") == 1800

    clock.advance(1799)  # t=2799: one second before the slid expiry, alive
    assert await load_selcrs(redis, sid, sliding_ttl=1800) == "[['a','b']]"
    # Activity at hard-cap minus epsilon cannot save it; the cap is absolute.
    clock.advance(7200 - 2799 + 1)  # past the hard cap measured from issuance
    assert await load_selcrs(redis, sid, sliding_ttl=1800) is None
    assert await redis.get(f"selcrs:{sid}") is None  # hard-expired jar is dropped


@pytest.mark.anyio
async def test_selcrs_hard_anchor_is_nx_at_issuance():
    clock, redis = _redis_with_clock()
    sid = "fixedsid"
    await store_selcrs(redis, sid, "one", sliding_ttl=1800, hard_ttl=7200)
    clock.advance(3000)
    # A same-id re-store overwrites the jar but must NOT push the hard cap out.
    await store_selcrs(redis, sid, "two", sliding_ttl=1800, hard_ttl=7200)
    assert await redis.get(f"selcrs:{sid}") == "two"
    assert redis.remaining_ttl(f"selcrs_hard:{sid}") == 7200 - 3000
