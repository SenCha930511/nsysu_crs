"""GET /api/schedule contract tests (always-200, cache-aside, breaker-gated).

Hermetic: scripted ``fetch_front_page`` stubs + FakeRedis, no Postgres, no
school contact. The fixture html is the live 115-1 front page.
"""

import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.auth.breaker import OPENED_AT_KEY, STREAK_KEY
from app.config import Settings
from app.main import create_app
from app.schedule.front import parse_front_schedule
from app.schedule.store import CACHE_KEY, FRESHNESS_SECONDS
from app.selcrs.errors import SelcrsUnavailable
from tests.fake_redis import FakeRedis

FIXTURE_HTML = (Path(__file__).parent / "fixtures" / "front_live_1151.html").read_text(
    encoding="utf-8"
)
TZ = ZoneInfo("Asia/Taipei")


@dataclass
class Harness:
    client: TestClient
    redis: FakeRedis
    school_calls: list[str]


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    settings = Settings(app_secret="schedule-api-test-secret")
    app = create_app(settings)
    redis = FakeRedis()
    calls: list[str] = []

    async def stub_fetch(*, transport=None) -> str:
        calls.append("fetch")
        return FIXTURE_HTML

    monkeypatch.setattr("app.api.schedule.fetch_front_page", stub_fetch)
    client = TestClient(app)
    client.__enter__()
    client.app.state.redis = redis
    box = Harness(client=client, redis=redis, school_calls=calls)
    yield box
    client.__exit__(None, None, None)


def _payload(*, fetched_at: datetime) -> dict[str, object]:
    schedule = parse_front_schedule(FIXTURE_HTML, tz=TZ)
    return {
        "fetched_at": fetched_at.isoformat(),
        "title": schedule.title,
        "events": [
            {
                "key": event.key,
                "label": event.label,
                "kind": event.kind,
                "start": event.start.isoformat(),
                "end": event.end.isoformat() if event.end is not None else None,
            }
            for event in schedule.events
        ],
    }


def _seed_stale_cache(redis: FakeRedis) -> None:
    old = datetime.now(TZ) - timedelta(seconds=FRESHNESS_SECONDS + 60)
    blob = json.dumps(_payload(fetched_at=old), ensure_ascii=False)
    redis._values[CACHE_KEY] = (blob, None)  # same direct-write idiom as sitewide tests


def test_cold_cache_fetches_then_serves_from_cache(harness: Harness) -> None:
    first = harness.client.get("/api/schedule")
    assert first.status_code == 200
    body = first.json()
    assert body["ok"] is True and body["stale"] is False
    assert body["title"] == "一佰一十五學年度第一學期選課日程"
    assert len(body["events"]) == 12
    assert body["events"][0]["key"] == "first_round_1"

    second = harness.client.get("/api/schedule")
    assert second.json()["ok"] is True
    assert len(harness.school_calls) == 1  # the fresh cache answered the 2nd hit


def test_stale_cache_triggers_refresh(harness: Harness) -> None:
    _seed_stale_cache(harness.redis)
    response = harness.client.get("/api/schedule")
    assert response.status_code == 200
    assert response.json()["stale"] is False
    assert len(harness.school_calls) == 1


def test_school_down_serves_last_good_stale(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_stale_cache(harness.redis)

    async def failing(*, transport=None) -> str:
        raise SelcrsUnavailable("scripted school timeout")

    monkeypatch.setattr("app.api.schedule.fetch_front_page", failing)
    response = harness.client.get("/api/schedule")
    body = response.json()
    assert response.status_code == 200
    assert body["ok"] is True and body["stale"] is True
    assert len(body["events"]) == 12
    assert harness.redis.peek(STREAK_KEY) == "1"  # failure fed the breaker streak


def test_school_down_cold_cache_reports_not_ok(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def failing(*, transport=None) -> str:
        raise SelcrsUnavailable("scripted school timeout")

    monkeypatch.setattr("app.api.schedule.fetch_front_page", failing)
    response = harness.client.get("/api/schedule")
    body = response.json()
    assert response.status_code == 200
    assert body["ok"] is False and body["stale"] is False
    assert body["events"] == []


def test_open_breaker_means_zero_school_contact(harness: Harness) -> None:
    harness.redis._values[OPENED_AT_KEY] = (repr(time.time()), None)
    response = harness.client.get("/api/schedule")
    body = response.json()
    assert response.status_code == 200
    assert body["ok"] is False
    assert harness.school_calls == []  # locally answered; the school never rang
