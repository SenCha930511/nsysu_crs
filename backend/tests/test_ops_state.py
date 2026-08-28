"""GET /api/ops/state (plan todo 17): public posture vs gated admin detail."""

import time
import uuid
from dataclasses import dataclass

import httpx
import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app.api.ops import is_admin
from app.auth.breaker import OPENED_AT_KEY, STREAK_KEY
from app.auth.students import LoginDbResult
from app.config import Settings
from app.main import create_app
from app.selcrs.endpoints import Sso2Result
from app.selcrs.errors import SelcrsUnavailable
from app.selcrs.sso2 import FAILURE_MARKER, Sso2Outcome
from tests.fake_redis import FakeRedis

SECRET = "qa17-ops-secret"


def _success_school():
    jar = httpx.Cookies()
    jar.set("ASPSESSIONIDQATEST", "qa17-cookie-value")
    return Sso2Result(outcome=Sso2Outcome.SUCCESS, cookies=jar, detail=None)


def _open_breaker_via_logins(harness) -> None:
    for _ in range(5):
        assert harness.post(
            "/api/auth/login", json={"student_no": "M153000024", "password": "x"}
        ).status_code == 503


def _lockout_via_logins(harness) -> None:
    for _ in range(5):
        assert harness.post(
            "/api/auth/login", json={"student_no": "M153000024", "password": "x"}
        ).status_code == 401


@dataclass
class Harness:
    client: TestClient
    redis: FakeRedis

    def post(self, path: str, **kw):
        return self.client.post(path, **kw)

    def admin_state(self):
        return self.client.get("/api/ops/state", headers={"X-App-Secret": SECRET}).json()


def _build_harness(monkeypatch, login_script) -> Harness:
    async def stub_login(student_no: str, password: str) -> Sso2Result:
        return login_script(student_no, password)

    async def stub_db(factory, student_no: str) -> LoginDbResult:
        return LoginDbResult(student_id=uuid.uuid4(), superseded_jobs=0)

    monkeypatch.setattr("app.api.auth.login_sso2", stub_login)
    monkeypatch.setattr("app.api.auth.record_successful_login", stub_db)
    app = create_app(Settings(app_secret=SECRET))
    client = TestClient(app)
    client.__enter__()
    harness = Harness(client=client, redis=FakeRedis())
    client.app.state.redis = harness.redis
    return harness


@pytest.fixture
def harness_factory(monkeypatch):
    built: list[Harness] = []

    def factory(login_script) -> Harness:
        harness = _build_harness(monkeypatch, login_script)
        built.append(harness)
        return harness

    yield factory
    for harness in built:
        harness.client.__exit__(None, None, None)


def test_public_posture_closed_breaker_shows_minimal_shape(harness_factory):
    # Given a closed breaker
    harness = harness_factory(lambda s, p: _success_school())

    # When a public client reads the state endpoint
    response = harness.client.get("/api/ops/state")

    # Then it sees only the coarse posture (nothing admin-only leaks)
    assert response.status_code == 200
    body = response.json()
    assert body["breaker"]["state"] == "closed"
    assert body["breaker"]["mode"] == "normal"
    assert body["breaker"]["streak"] is None
    assert body["breaker"]["opened_at"] is None
    assert body["lockouts"] is None


def test_open_breaker_is_visible_publicly_detail_stays_gated(harness_factory):
    # Given the breaker opened by five transport failures
    def unknown(s, p):
        raise SelcrsUnavailable("scripted outage")

    harness = harness_factory(unknown)
    _open_breaker_via_logins(harness)

    # When a public client reads the state
    public = harness.client.get("/api/ops/state").json()
    # Then the degraded posture is exactly what the banner needs
    assert public["breaker"]["state"] == "open"
    assert public["breaker"]["mode"] == "read-only"
    assert public["breaker"]["streak"] is None  # internals stay gated
    assert public["lockouts"] is None

    # And a wrong secret is no better than none
    wrong = harness.client.get(
        "/api/ops/state", headers={"X-App-Secret": "wrong-" + SECRET}
    ).json()
    assert wrong == public

    # But the gated read carries the internals
    admin = harness.admin_state()
    assert admin["breaker"]["streak"] == 5
    assert admin["breaker"]["failure_threshold"] == 5
    assert admin["breaker"]["recovery_after"] == 300
    assert admin["breaker"]["probe_gate_seconds"] == 60
    assert isinstance(admin["breaker"]["opened_at"], str)
    assert admin["lockouts"] == {"today": 0, "yesterday": 0, "total": 0}


def test_half_open_after_the_wait_reports_half_open(harness_factory):
    def unknown(s, p):
        raise SelcrsUnavailable("scripted outage")

    harness = harness_factory(unknown)
    _open_breaker_via_logins(harness)

    # Simulated elapsed wait (the opened stamp lies in the past)
    harness.redis._values[OPENED_AT_KEY] = (repr(time.time() - 301), None)
    assert harness.client.get("/api/ops/state").json()["breaker"]["state"] == "half-open"
    # Reporting never consumed the probe gate or cleared anything
    assert harness.redis.peek(STREAK_KEY) == "5"
    assert harness.client.get("/api/ops/state").json()["breaker"]["state"] == "half-open"


def test_new_lockout_events_surface_under_the_gate(harness_factory):
    # Given a school that always verdicts CREDENTIAL-FAIL
    def cred_fail(s, p):
        return Sso2Result(
            outcome=Sso2Outcome.CREDENTIAL_FAIL, cookies=httpx.Cookies(), detail=FAILURE_MARKER
        )

    harness = harness_factory(cred_fail)

    # When five failures trigger the fixed lock
    _lockout_via_logins(harness)

    # Then the admin read counts exactly one new lock event
    assert harness.admin_state()["lockouts"] == {"today": 1, "yesterday": 0, "total": 1}
    # Public clients still see nothing of it
    assert harness.client.get("/api/ops/state").json()["lockouts"] is None


def test_is_admin_gate_matrix():
    settings = Settings(app_secret=SECRET)

    def request_with(headers: dict[str, str], client_host: str) -> Request:
        raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
        return Request(
            {"type": "http", "method": "GET", "headers": raw, "client": (client_host, 1234)}
        )

    # Gate passes: exact secret (any client host), or bare loopback peer
    assert is_admin(request_with({"X-App-Secret": SECRET}, "10.0.0.9"), settings)
    assert is_admin(request_with({}, "127.0.0.1"), settings)
    assert is_admin(request_with({}, "::1"), settings)
    # Gate refuses: wrong/empty secret from a non-loopback (proxied) host
    assert not is_admin(request_with({"X-App-Secret": SECRET + "x"}, "10.0.0.9"), settings)
    assert not is_admin(request_with({}, "10.0.0.9"), settings)
    assert not is_admin(request_with({}, "172.18.0.6"), settings)  # e.g. Caddy's peer IP
