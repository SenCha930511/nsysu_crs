"""Selections endpoint contract tests (plan todo 9; QA qa/09-parse.log part 2).

Fully hermetic, patterned on test_auth_api.py: the school is a scripted
``get_slt_result`` stub (monkeypatched at app.api.selections), Redis is
FakeRedis, and the courses join is a recording stub (the real join runs in
the live QA sync against the 2596-row compose catalog). Sessions are seeded
directly via create_site_session + store_selcrs - no password exists here.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.auth.sessions import create_site_session, store_selcrs
from app.config import Settings
from app.main import create_app
from app.selections.parse import SelectionItem, parse_slt_result
from app.selections.store import SelectionsSnapshot, store_snapshot
from app.selcrs.errors import SelcrsUnavailable

from tests.fake_redis import FakeRedis

FIXTURES = Path(__file__).parent / "fixtures"
TEST_COOKIE_VALUE = "QA-SECRET-COOKIE-6b7a5941e3"

SchoolScript = Callable[[httpx.Cookies], str]


@dataclass
class StubSchool:
    """Scriptable stand-in for adapter get_slt_result; counts every call."""

    script: SchoolScript
    calls: int = 0

    async def __call__(self, cookies: httpx.Cookies) -> str:
        self.calls += 1
        return self.script(cookies)


def _live_page(cookies: httpx.Cookies) -> str:
    return (FIXTURES / "slt_result_live_1151.html").read_bytes().decode("utf-8")


def _login_bounce(cookies: httpx.Cookies) -> str:
    return '<html><body><form action="Studcheck_sso2.asp">請先登錄</form></body></html>'


def _unknown_shape(cookies: httpx.Cookies) -> str:
    raise SelcrsUnavailable("scripted unknown school shape")


@dataclass
class Harness:
    client: TestClient
    redis: FakeRedis
    school: StubSchool
    join_codes_seen: list[list[str]] = field(default_factory=list)
    join_matches: dict[str, str] = field(default_factory=dict)

    async def seed_session(self, *, with_jar: bool = True) -> str:
        """A live site session (with a parked selcrs jar unless told otherwise)."""
        session_id = await create_site_session(self.redis, "M153000024")
        if with_jar:
            jar = httpx.Cookies()
            jar.set("ASPSESSIONIDQATEST", TEST_COOKIE_VALUE)
            await store_selcrs(
                self.redis,
                session_id,
                '[["ASPSESSIONIDQATEST", "' + TEST_COOKIE_VALUE + '"]]',
                sliding_ttl=1800,
                hard_ttl=7200,
            )
        return session_id


def _make_harness(monkeypatch, script: SchoolScript, matches=None) -> Harness:
    settings = Settings(app_secret="qa09-test-secret")
    app = create_app(settings)
    school = StubSchool(script)
    redis = FakeRedis()
    harness = Harness(client=TestClient(app), redis=redis, school=school)

    async def stub_attach(db, *, year_sem, items):
        harness.join_codes_seen.append(sorted(i.code for i in items if i.code))
        matched = harness.join_matches
        return [
            item.model_copy(
                update={
                    "course_id": matched.get(item.code) if item.code else None,
                    "unknown": item.code not in matched if item.code else True,
                }
            )
            for item in items
        ]

    monkeypatch.setattr("app.api.selections.get_slt_result", school)
    monkeypatch.setattr("app.api.selections.attach_course_matches", stub_attach)
    if matches:
        harness.join_matches.update(matches)
    harness.client.__enter__()
    harness.client.app.state.redis = redis
    return harness


@pytest.fixture
def harness_factory(monkeypatch):
    built: list[Harness] = []

    def factory(script: SchoolScript, **kwargs) -> Harness:
        harness = _make_harness(monkeypatch, script, **kwargs)
        built.append(harness)
        return harness

    yield factory
    for harness in built:
        harness.client.__exit__(None, None, None)


async def _seed_and_sync(harness: Harness) -> tuple[str, httpx.Response]:
    sid = await harness.seed_session()
    return sid, harness.client.post("/api/me/selections/sync", cookies={"session_id": sid})


# ---------- happy path (QA qa/09-parse.log part 2) ----------


@pytest.mark.anyio
async def test_sync_real_fixture_caches_session_scoped_snapshot(harness_factory):
    # Given a live session and the school answering the REAL 115-1 page
    harness = harness_factory(_live_page)

    # When the student syncs
    sid, response = await _seed_and_sync(harness)

    # Then the response carries every parsed row with the diff + synced_at
    assert response.status_code == 200
    body = response.json()
    assert body["synced_at"] and body["items"]
    assert len(body["items"]) == 7
    assert {item["state"] for item in body["items"]} == {"選上", "失敗"}
    # first sync: everything added, nothing removed/unchanged
    assert len(body["added"]) == 7
    assert body["removed"] == [] and body["unchanged"] == []

    # And the snapshot landed under the SITE SESSION key only (7d TTL)
    assert harness.redis.remaining_ttl(f"selections:{sid}") == 7 * 24 * 3600

    # And GET serves the same snapshot without touching the school again
    got = harness.client.get("/api/me/selections", cookies={"session_id": sid})
    assert got.status_code == 200
    assert got.json()["synced_at"] == body["synced_at"]
    assert got.json()["items"] == body["items"]
    assert harness.school.calls == 1


@pytest.mark.anyio
async def test_sync_unknown_join_never_drops_unmatched_rows(harness_factory):
    # Given the catalog join matches nothing (courses.code is all NULL today)
    harness = harness_factory(_live_page)

    # When sync runs
    sid, response = await _seed_and_sync(harness)

    # Then the join WAS attempted with the 5 real codes, did not error, and
    # all rows survive with unknown=true
    assert response.status_code == 200
    items = response.json()["items"]
    assert harness.join_codes_seen == [
        ["M30400B1", "M3046243", "M3046255", "M3046327", "M3046353"]
    ]
    assert len(items) == 7 and all(item["unknown"] for item in items)
    assert all(item["course_id"] is None for item in items)


@pytest.mark.anyio
async def test_sync_marks_matched_courses_when_catalog_knows_the_code(harness_factory):
    # Given a catalog that (hypothetically) knows one code
    known = str(uuid.uuid4())
    harness = harness_factory(_live_page, matches={"M3046243": known})

    _sid, response = await _seed_and_sync(harness)
    items = {(i["state"], i["course_no"]): i for i in response.json()["items"]}
    assert items[("選上", "CSE515")]["unknown"] is False
    assert items[("選上", "CSE515")]["course_id"] == known
    assert items[("失敗", "CSE530")]["unknown"] is True  # code-less row


# ---------- frozen diff (seeded previous snapshot) ----------


@pytest.mark.anyio
async def test_frozen_sync_diff_against_seeded_snapshot(harness_factory):
    # Given a previous snapshot: one still-selected course + one dropped one
    harness = harness_factory(_live_page)
    sid = await harness.seed_session()
    prior = SelectionsSnapshot(
        synced_at="2026-08-20T09:00:00+08:00",
        items=[
            item
            for raw in (
                '{"code": "M3046243", "course_no": "CSE515", "state": "選上", '
                '"dept": "資工碩", "name": "高等電腦網路", "credit": 3, '
                '"compulsory_elective": "必", "teacher": "林俊宏", '
                '"room_text": "三2,3,4(工EC 5012)", "points_priority": 0, '
                '"stage": "0", "year_semest_note": "期", "times": "三2,3,4", '
                '"room": "工EC 5012", "unknown": true, "course_id": null}',
                '{"code": null, "course_no": "CSE999", "state": "選上", '
                '"dept": "資工碩", "name": "已退舊課", "credit": 2, '
                '"compulsory_elective": "選", "teacher": "某人", "room_text": "", '
                '"points_priority": null, "stage": "0", "year_semest_note": "期", '
                '"times": null, "room": null, "unknown": true, "course_id": null}',
            )
            for item in (SelectionItem.model_validate_json(raw),)
        ],
    )
    await store_snapshot(harness.redis, sid, prior)

    # When sync runs against the real fixture
    response = harness.client.post("/api/me/selections/sync", cookies={"session_id": sid})
    body = response.json()

    # Then the diff is exact: M3046243 unchanged, the 6 newcomers added,
    # CSE999 removed (old version reported), synced_at moved forward
    assert [i["code"] for i in body["unchanged"]] == ["M3046243"]
    assert [i["course_no"] for i in body["removed"]] == ["CSE999"]
    assert len(body["added"]) == 6
    assert len(body["items"]) == 7
    assert body["synced_at"] != "2026-08-20T09:00:00+08:00"


# ---------- expired school session -> 401 SELCRS_EXPIRED (QA qa/09-expired.log) ----------


@pytest.mark.anyio
async def test_login_page_bounce_is_401_selcrs_expired_and_keeps_old_snapshot(
    harness_factory,
):
    # Given a synced session whose school cookie has since died
    harness = harness_factory(_live_page)
    sid, _ = await _seed_and_sync(harness)
    cached = harness.redis.peek(f"selections:{sid}")
    assert cached is not None

    # When the school now bounces to its login page
    harness.school.script = _login_bounce
    response = harness.client.post(
        "/api/me/selections/sync", cookies={"session_id": sid}
    )

    # Then 401 SELCRS_EXPIRED and the previous snapshot is NOT clobbered
    assert response.status_code == 401
    assert response.json() == {"detail": "SELCRS_EXPIRED"}
    assert harness.redis.peek(f"selections:{sid}") == cached


@pytest.mark.anyio
async def test_missing_selcrs_jar_is_401_selcrs_expired_with_zero_school_calls(
    harness_factory,
):
    # Given a site session with NO parked jar (sliding/hard TTL lapsed)
    harness = harness_factory(_live_page)
    sid = await harness.seed_session(with_jar=False)

    response = harness.client.post("/api/me/selections/sync", cookies={"session_id": sid})

    assert response.status_code == 401
    assert response.json() == {"detail": "SELCRS_EXPIRED"}
    assert harness.school.calls == 0


@pytest.mark.anyio
async def test_unknown_school_shape_is_503_never_401(harness_factory):
    harness = harness_factory(_unknown_shape)
    sid, response = await _seed_and_sync(harness)
    assert response.status_code == 503
    assert response.json() == {"detail": "school_unavailable"}
    assert harness.redis.peek(f"selections:{sid}") is None


# ---------- cache policy: purged on logout; empty pre-sync ----------


@pytest.mark.anyio
async def test_cache_purged_on_logout(harness_factory):
    # Given a synced session
    harness = harness_factory(_live_page)
    sid, sync = await _seed_and_sync(harness)
    assert sync.status_code == 200
    assert harness.redis.keys_with_prefix(f"selections:{sid}")

    # When the student logs out
    out = harness.client.post("/api/auth/logout", cookies={"session_id": sid})
    assert out.status_code == 200

    # Then the selections row is purged with the rest of the session
    assert harness.redis.keys_with_prefix(f"selections:{sid}") == []
    got = harness.client.get("/api/me/selections", cookies={"session_id": sid})
    assert got.status_code == 401  # session itself is gone too


@pytest.mark.anyio
async def test_get_selections_is_empty_before_first_sync(harness_factory):
    harness = harness_factory(_live_page)
    sid = await harness.seed_session()
    response = harness.client.get("/api/me/selections", cookies={"session_id": sid})
    assert response.status_code == 200
    assert response.json() == {"synced_at": None, "items": []}
    assert harness.school.calls == 0  # GET never touches the school


def test_endpoints_require_a_site_session(harness_factory):
    harness = harness_factory(_live_page)
    assert harness.client.post("/api/me/selections/sync").status_code == 401
    assert harness.client.get("/api/me/selections").json() == {
        "detail": "not_authenticated"
    }
