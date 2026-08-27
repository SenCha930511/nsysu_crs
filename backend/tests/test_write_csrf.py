"""CSRF double-submit tests (plan todo 14; QA qa/14-csrf.log part).

Cookie ``csrf_{session_id}`` (httpOnly+Secure+SameSite=Lax, TTL 900) minted
at login and echoed in the body (the cookie is httpOnly by spec, so the SPA
learns the value from that same-origin body channel); every /api/write/*
call must repeat it as ``X-CSRF-Token`` else 403 csrf_failed; fresh login
rotates; logout deletes; success re-sets it with a fresh 900s (sliding).
"""

import json
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.auth.sessions import create_site_session, store_selcrs
from app.auth.students import LoginDbResult
from app.config import Settings
from app.main import create_app
from app.selcrs.endpoints import Sso2Result
from app.selcrs.sso2 import Sso2Outcome
from app.write.csrf import csrf_cookie_name
from tests.fake_redis import FakeRedis

FIXTURES = Path(__file__).parent / "fixtures"
TEST_COOKIE_VALUE = "QA-SECRET-COOKIE-6b7a5941e3"
STUDENT = "M153000024"
PASSWORD = "QA14-mock-password"


async def _sso2_success(student_no: str, password: str) -> Sso2Result:
    jar = httpx.Cookies()
    jar.set("ASPSESSIONIDQATEST", TEST_COOKIE_VALUE)
    return Sso2Result(outcome=Sso2Outcome.SUCCESS, cookies=jar, detail=None)


@dataclass
class Rig:
    client: TestClient
    redis: FakeRedis
    studfun_calls: int = 0

    def login(self) -> httpx.Response:
        return self.client.post(
            "/api/auth/login", json={"student_no": STUDENT, "password": PASSWORD}
        )

    async def seed_session(self) -> str:
        session_id = await create_site_session(self.redis, STUDENT)
        await store_selcrs(
            self.redis,
            session_id,
            json.dumps([["ASPSESSIONIDQATEST", TEST_COOKIE_VALUE]]),
            sliding_ttl=1800,
            hard_ttl=7200,
        )
        return session_id

    def preview(self, session_id: str, csrf: str | None, header: object = ...) -> httpx.Response:
        cookies = {"session_id": session_id}
        if csrf is not None:
            cookies[csrf_cookie_name(session_id)] = csrf
        headers = {} if header is ... else {"X-CSRF-Token": header}
        return self.client.post(
            "/api/write/preview",
            json={"ops": [{"action": "+", "course_id": "GEAE2526", "priority": 1}]},
            cookies=cookies,
            headers=headers,
        )


def _make_rig(monkeypatch) -> Rig:
    settings = Settings(app_secret="qa14-csrf-secret")
    app = create_app(settings)
    rig = Rig(client=TestClient(app), redis=FakeRedis())

    async def stub_record(factory, student_no: str) -> LoginDbResult:
        return LoginDbResult(student_id=uuid.uuid4(), superseded_jobs=0)

    async def stub_studfun() -> str:
        rig.studfun_calls += 1
        return (FIXTURES / "studfun_closed_live_1151.html").read_bytes().decode("utf-8")

    monkeypatch.setattr("app.api.auth.login_sso2", _sso2_success)
    monkeypatch.setattr("app.api.auth.record_successful_login", stub_record)
    monkeypatch.setattr("app.api.write_probe.get_studfun", stub_studfun)
    rig.client.__enter__()
    rig.client.app.state.redis = rig.redis
    return rig


@pytest.fixture
def rig_factory(monkeypatch):
    built: list[Rig] = []

    def factory() -> Rig:
        rig = _make_rig(monkeypatch)
        built.append(rig)
        return rig

    yield factory
    for rig in built:
        rig.client.__exit__(None, None, None)


def _session_id(set_cookies: list[str]) -> str:
    for header in set_cookies:
        for part in header.split("; "):
            if part.startswith("session_id="):
                return part[len("session_id=") :]
    raise AssertionError(f"no session_id cookie in {set_cookies}")


def _csrf_cookie(set_cookies: list[str], session_id: str) -> str:
    prefix = f"{csrf_cookie_name(session_id)}="
    for header in set_cookies:
        if header.startswith(prefix):
            return header
    raise AssertionError(f"no csrf cookie for {session_id} in {set_cookies}")


# ---------- login / rotation / logout ----------


def test_login_sets_flagged_csrf_cookie_and_echoes_body_token(rig_factory):
    rig = rig_factory()
    response = rig.login()
    assert response.status_code == 200

    cookies = response.headers.get_list("set-cookie")
    sid = _session_id(cookies)
    cookie = _csrf_cookie(cookies, sid)
    for flag in ("HttpOnly", "Secure", "SameSite=lax", "Max-Age=900", "Path=/"):
        assert flag in cookie, cookie
    # httpOnly by spec -> the SPA learns the value from the login body,
    # and the two MUST be the same opaque token.
    token = response.json()["csrf_token"]
    assert token and cookie.split("; ")[0] == f"{csrf_cookie_name(sid)}={token}"


def test_fresh_login_rotates_the_token(rig_factory):
    rig = rig_factory()
    first = rig.login()
    second = rig.login()
    first_sid = _session_id(first.headers.get_list("set-cookie"))
    second_sid = _session_id(second.headers.get_list("set-cookie"))
    assert first_sid != second_sid  # a fresh session every login
    assert first.json()["csrf_token"] != second.json()["csrf_token"]


@pytest.mark.anyio
async def test_logout_deletes_the_csrf_cookie(rig_factory):
    rig = rig_factory()
    login = rig.login()
    sid = _session_id(login.headers.get_list("set-cookie"))

    out = rig.client.post("/api/auth/logout", cookies={"session_id": sid})

    cookies = out.headers.get_list("set-cookie")
    expired = _csrf_cookie(cookies, sid)
    assert "Max-Age=0" in expired or "Expires=" in expired


# ---------- the /api/write/* double-submit gate ----------


@pytest.mark.anyio
async def test_missing_header_is_403_and_never_touches_the_school(rig_factory):
    rig = rig_factory()
    sid = await rig.seed_session()
    response = rig.preview(sid, "valid-token")  # cookie set, header omitted
    assert response.status_code == 403
    assert response.json() == {"detail": "csrf_failed"}
    assert rig.studfun_calls == 0


@pytest.mark.anyio
async def test_wrong_token_is_403_and_never_touches_the_school(rig_factory):
    rig = rig_factory()
    sid = await rig.seed_session()
    response = rig.preview(sid, "valid-token", header="wrong-token")
    assert response.status_code == 403
    assert response.json() == {"detail": "csrf_failed"}
    assert rig.studfun_calls == 0


@pytest.mark.anyio
async def test_right_token_passes_and_slides_the_cookie_ttl(rig_factory):
    rig = rig_factory()
    sid = await rig.seed_session()
    response = rig.preview(sid, "valid-token", header="valid-token")

    assert response.status_code == 409  # closed stage stub: middleware passed
    assert response.json()["detail"] == "stage_unavailable"
    assert rig.studfun_calls == 1
    cookie = _csrf_cookie(response.headers.get_list("set-cookie"), sid)
    assert cookie.startswith(f"{csrf_cookie_name(sid)}=valid-token")
    assert "Max-Age=900" in cookie  # sliding refresh, value unchanged


@pytest.mark.anyio
async def test_no_session_cookie_at_all_is_403_not_401(rig_factory):
    rig = rig_factory()
    response = rig.client.post(
        "/api/write/preview",
        json={"ops": [{"action": "+", "course_id": "GEAE2526", "priority": 1}]},
        headers={"X-CSRF-Token": "whatever"},
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "csrf_failed"}


def test_read_routes_are_not_gated(rig_factory):
    rig = rig_factory()
    response = rig.client.get("/api/stage")  # no cookies, no CSRF header
    assert response.status_code == 401  # plain auth behavior, never 403
