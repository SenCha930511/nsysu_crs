"""Auth endpoint contract tests (plan todo 8; QA qa/08-login-ok.log / lockout / unknown).

Fully hermetic: the school is a scripted ``login_sso2`` stub (monkeypatched at
app.api.auth), Redis is FakeRedis, and the Postgres write behind a successful
login is replaced by a recording stub (the real SQL is pinned separately in
test_auth_db.py against compose Postgres).
"""

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx
import pytest
from fastapi.testclient import TestClient

from app.auth.students import LoginDbResult
from app.config import Settings
from app.main import create_app
from app.selcrs.endpoints import Sso2Result
from app.selcrs.errors import SelcrsUnavailable
from app.selcrs.sso2 import FAILURE_MARKER, Sso2Outcome
from app.selcrs.transform import base64md5

from tests.fake_redis import FakeRedis

TEST_PASSWORD = "Xq9-TestPw-77z!"
TEST_COOKIE_VALUE = "QA-SECRET-COOKIE-9f8e7d6c"

SchoolScript = Callable[[str, str], Sso2Result]


@dataclass
class StubSchool:
    """Scriptable stand-in for adapter login_sso2; counts every school call."""

    script: SchoolScript
    calls: list[tuple[str, str]] = field(default_factory=list)

    async def __call__(self, student_no: str, password: str) -> Sso2Result:
        self.calls.append((student_no, password))
        return self.script(student_no, password)


def _succeed(student_no: str, password: str) -> Sso2Result:
    jar = httpx.Cookies()
    jar.set("ASPSESSIONIDQATEST", TEST_COOKIE_VALUE)
    jar.set("BIGipServerPL-Selcrs", "pool-cookie-value")
    return Sso2Result(outcome=Sso2Outcome.SUCCESS, cookies=jar, detail=None)


def _credential_fail(student_no: str, password: str) -> Sso2Result:
    return Sso2Result(
        outcome=Sso2Outcome.CREDENTIAL_FAIL, cookies=httpx.Cookies(), detail=FAILURE_MARKER
    )


def _unknown(student_no: str, password: str) -> Sso2Result:
    raise SelcrsUnavailable("scripted unknown school shape")


@dataclass
class Harness:
    client: TestClient
    redis: FakeRedis
    school: StubSchool
    db_logins: list[str]

    def login(self, student_no: str = "M153000024", password: str = TEST_PASSWORD):
        return self.client.post(
            "/api/auth/login", json={"student_no": student_no, "password": password}
        )

    def session_id(self, response) -> str:
        cookie = response.headers["set-cookie"]
        prefix = "session_id="
        return next(
            part[len(prefix) :]
            for part in cookie.split("; ")
            if part.startswith(prefix)
        )


def _make_harness(monkeypatch, script: SchoolScript, **settings_overrides) -> Harness:
    settings = Settings(app_secret="qa08-test-secret", **settings_overrides)
    app = create_app(settings)
    school = StubSchool(script)
    db_logins: list[str] = []

    async def stub_record_successful_login(factory, student_no: str) -> LoginDbResult:
        db_logins.append(student_no)
        return LoginDbResult(student_id=uuid.uuid4(), superseded_jobs=0)

    monkeypatch.setattr("app.api.auth.login_sso2", school)
    monkeypatch.setattr("app.api.auth.record_successful_login", stub_record_successful_login)
    client = TestClient(app)
    client.__enter__()
    harness = Harness(client=client, redis=FakeRedis(), school=school, db_logins=db_logins)
    client.app.state.redis = harness.redis
    return harness


@pytest.fixture
def harness_factory(monkeypatch):
    built: list[Harness] = []

    def factory(script: SchoolScript, **overrides) -> Harness:
        harness = _make_harness(monkeypatch, script, **overrides)
        built.append(harness)
        return harness

    yield factory
    for harness in built:
        harness.client.__exit__(None, None, None)


# ---------- SUCCESS flow (QA qa/08-login-ok.log) ----------


def test_login_success_issues_flagged_cookie_and_parks_selcrs_in_redis(harness_factory):
    # Given a school that answers SSO2 SUCCESS
    harness = harness_factory(_succeed)

    # When the student logs in
    response = harness.login()

    # Then the contract holds end to end
    assert response.status_code == 200
    assert response.json() == {"student_no": "M153000024"}
    cookie = response.headers["set-cookie"]
    for flag in ("session_id=", "HttpOnly", "Secure", "SameSite=lax", "Path=/"):
        assert flag in cookie, cookie
    # adapter saw the RAW password exactly once, in memory only
    assert harness.school.calls == [("M153000024", TEST_PASSWORD)]

    sid = harness.session_id(response)
    assert harness.redis.remaining_ttl(f"site_session:{sid}") == 7 * 24 * 3600
    assert harness.redis.remaining_ttl(f"selcrs:{sid}") == 1800
    assert harness.redis.remaining_ttl(f"selcrs_hard:{sid}") == 7200
    assert TEST_COOKIE_VALUE in (harness.redis.peek(f"selcrs:{sid}") or "")
    assert harness.db_logins == ["M153000024"]  # upsert + supersede ran


def test_me_roundtrip_and_logout_clears_everything(harness_factory):
    # Given a live session
    harness = harness_factory(_succeed)
    sid = harness.session_id(harness.login())

    # When me / logout / me again
    me = harness.client.get("/api/auth/me", cookies={"session_id": sid})
    assert me.status_code == 200 and me.json() == {"student_no": "M153000024"}
    out = harness.client.post("/api/auth/logout", cookies={"session_id": sid})
    assert out.status_code == 200
    gone = harness.client.get("/api/auth/me", cookies={"session_id": sid})

    # Then the session is dead and every Redis row for it is gone
    assert gone.status_code == 401 and gone.json() == {"detail": "not_authenticated"}
    assert harness.redis.keys_with_prefix(f"site_session:{sid}") == []
    assert harness.redis.keys_with_prefix(f"selcrs") == []
    assert "session_id=" in out.headers["set-cookie"]  # cookie re-issued expired


def test_me_missing_and_bogus_session_fail_identically(harness_factory):
    harness = harness_factory(_succeed)
    missing = harness.client.get("/api/auth/me")
    bogus = harness.client.get("/api/auth/me", cookies={"session_id": "nope"})
    assert (missing.status_code, missing.json()) == (401, {"detail": "not_authenticated"})
    assert bogus.json() == missing.json()  # presence/expiry indistinguishable


# ---------- CREDENTIAL-FAIL + sliding-log lockout (QA qa/08-lockout.log) ----------


def test_credential_fail_is_401_with_school_marker_and_no_session(harness_factory):
    harness = harness_factory(_credential_fail)
    response = harness.login(student_no="M999999999")

    assert response.status_code == 401
    assert response.json() == {
        "detail": "invalid_credentials",
        "school_msg": FAILURE_MARKER,
    }
    assert "set-cookie" not in response.headers
    assert harness.redis.zcount_peek("loginfail:M999999999") == 1
    assert harness.redis.peek("breaker:school:streak") is None


def test_wrong_password_and_no_such_student_are_indistinguishable(harness_factory):
    harness = harness_factory(_credential_fail)
    wrong = harness.login(student_no="M153000024")
    nosuch = harness.login(student_no="M000000000")
    assert wrong.status_code == nosuch.status_code == 401
    assert wrong.json() == nosuch.json()


def test_fifth_failure_locks_and_locked_attempts_never_reach_school(harness_factory):
    harness = harness_factory(_credential_fail)

    # Given five real credential verdicts
    for _ in range(5):
        assert harness.login().status_code == 401
    assert harness.school.calls.__len__() == 5
    assert harness.redis.keys_with_prefix("loginlock:M153000024")

    # When the 6th attempt arrives it is locally 429-rejected BEFORE school
    blocked = harness.login()
    # Then: still 5 school calls, still 5 log entries (no append, no call)
    assert blocked.status_code == 429 and blocked.json() == {"detail": "too_many_attempts"}
    assert len(harness.school.calls) == 5
    assert harness.redis.zcount_peek("loginfail:M153000024") == 5

    # And the lock is per-account: another student still reaches the school
    other = harness.login(student_no="M153040025")
    assert other.status_code == 401
    assert len(harness.school.calls) == 6


def test_success_never_clears_the_failure_log(harness_factory):
    # Given three failures on record
    harness = harness_factory(_credential_fail)
    for _ in range(3):
        harness.login()

    # When the student then logs in successfully
    harness.school.script = _succeed
    assert harness.login(password="correct-now").status_code == 200

    # Then the old failures still stand (attacker budget is NOT refunded)
    assert harness.redis.zcount_peek("loginfail:M153000024") == 3


# ---------- UNKNOWN -> breaker (QA qa/08-unknown.log) ----------


def test_unknown_is_503_feeding_breaker_never_lockout(harness_factory):
    harness = harness_factory(_unknown)
    response = harness.login()

    assert response.status_code == 503 and response.json() == {"detail": "school_unavailable"}
    assert harness.redis.zcount_peek("loginfail:M153000024") == 0  # never an account signal
    assert harness.redis.keys_with_prefix("loginlock:") == []
    assert harness.redis.peek("breaker:school:streak") == "1"


def test_breaker_open_serves_local_503_with_zero_school_calls(harness_factory):
    # Given five straight UNKNOWN school responses: the breaker is open
    harness = harness_factory(_unknown)
    for _ in range(5):
        assert harness.login().status_code == 503
    assert len(harness.school.calls) == 5

    # When further attempts arrive they are answered locally: ZERO outbound
    for _ in range(3):
        assert harness.login().status_code == 503
    assert len(harness.school.calls) == 5  # the load-bearing assertion
    assert harness.redis.keys_with_prefix("loginfail:") == []


# ---------- IP secondary limit ----------


def test_ip_limit_counts_every_attempt_in_the_clock_hour(harness_factory):
    harness = harness_factory(_credential_fail, login_ip_hourly_limit=3)

    # Given three attempts (all counted, all reach the school)
    for _ in range(3):
        assert harness.login().status_code == 401
    # When the 4th arrives, the inclusive count crosses the limit
    blocked = harness.login()
    # Then 429 and the school was not consulted again
    assert blocked.status_code == 429
    assert len(harness.school.calls) == 3
    ip_keys = harness.redis.keys_with_prefix("loginip:")
    assert len(ip_keys) == 1  # one fixed clock-hour bucket for this IP


# ---------- body hygiene (grep test; QA qa/08-login-ok.log part 2) ----------


def test_no_password_or_cookie_value_leaks_into_any_log(harness_factory, caplog):
    # Given credentials with uniquely greppable values
    harness = harness_factory(_succeed)
    transformed = base64md5(TEST_PASSWORD)

    # When the whole login -> me -> logout round trip runs at DEBUG capture
    with caplog.at_level(logging.DEBUG):
        response = harness.login()
        sid = harness.session_id(response)
        harness.client.get("/api/auth/me", cookies={"session_id": sid})
        harness.client.post("/api/auth/logout", cookies={"session_id": sid})
        harness_factory(_credential_fail).login(password=TEST_PASSWORD)

    # Then neither the password (raw or base64md5) nor any cookie value appears
    for secret in (TEST_PASSWORD, transformed, TEST_COOKIE_VALUE, sid):
        assert secret not in caplog.text
    # And request validation error paths echo no password either
    bad = harness.client.post(
        "/api/auth/login", json={"student_no": "M1", "password": TEST_PASSWORD, "extra": "x"}
    )
    assert TEST_PASSWORD not in bad.text


def test_login_rejects_malformed_bodies(harness_factory):
    harness = harness_factory(_succeed)
    assert harness.client.post("/api/auth/login", json={"password": "x"}).status_code == 422
    assert harness.client.post(
        "/api/auth/login", json={"student_no": " ", "password": "x"}
    ).status_code == 400
    empty_pw = harness.client.post(
        "/api/auth/login", json={"student_no": "M153000024", "password": ""}
    )
    assert empty_pw.status_code == 422
