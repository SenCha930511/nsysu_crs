"""Runtime year-semester resolution (app.semester): override > Redis cache >
live school discovery > degrade to None (never guess)."""

from collections.abc import Awaitable, Callable

import pytest

from app.catalog.discover import DiscoveryError
from app.config import Settings
from app.selcrs.errors import SelcrsUnavailable
from app.semester import (
    SEMESTER_CACHE_KEY,
    SEMESTER_CACHE_TTL_SECONDS,
    resolve_year_sem,
)
from tests.fake_redis import FakeRedis


def _settings(semester: str | None = None) -> Settings:
    return Settings(app_secret="semester-resolver-secret", semester_year_sem=semester)


@pytest.fixture
def redis() -> FakeRedis:
    return FakeRedis()


@pytest.mark.anyio
async def test_explicit_override_wins(
    redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _boom() -> str:
        raise AssertionError("discovery must not run under an explicit override")

    monkeypatch.setattr("app.semester.discover_current_d0", _boom)
    assert await resolve_year_sem(redis, _settings("1152")) == "1152"


@pytest.mark.anyio
async def test_cache_hit_short_circuits_discovery(
    redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _boom() -> str:
        raise AssertionError("discovery must not run on a cache hit")

    await redis.set(SEMESTER_CACHE_KEY, "1151", ex=SEMESTER_CACHE_TTL_SECONDS)
    monkeypatch.setattr("app.semester.discover_current_d0", _boom)
    assert await resolve_year_sem(redis, _settings()) == "1151"


@pytest.mark.anyio
async def test_cache_miss_discovers_and_caches(
    redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.semester.discover_current_d0", _discover("1152"))
    assert await resolve_year_sem(redis, _settings()) == "1152"
    assert redis.peek(SEMESTER_CACHE_KEY) == "1152"
    assert redis.remaining_ttl(SEMESTER_CACHE_KEY) == SEMESTER_CACHE_TTL_SECONDS


def _discover(value: str) -> Callable[[], Awaitable[str]]:
    async def _inner() -> str:
        return value

    return _inner


@pytest.mark.anyio
@pytest.mark.parametrize(
    "failure_kind", ["discovery", "transport"], ids=["discovery", "transport"]
)
async def test_discovery_failure_degrades_to_none(
    redis: FakeRedis, monkeypatch: pytest.MonkeyPatch, failure_kind: str
) -> None:
    async def _raise() -> str:
        if failure_kind == "discovery":
            raise DiscoveryError("no YRSM select on page")
        raise SelcrsUnavailable("school unreachable")

    monkeypatch.setattr("app.semester.discover_current_d0", _raise)
    assert await resolve_year_sem(redis, _settings()) is None
    assert redis.peek(SEMESTER_CACHE_KEY) is None
