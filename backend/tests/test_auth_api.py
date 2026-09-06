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
from app.stuenroll.pipeline import FanoutLeg, FanoutResult, LegError
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


def _cookie_flags(set_cookie_header: str) -> list[str]:
    return [part.strip() for part in set_cookie_header.split(";")]


def _make_harness(
    monkeypatch,
    script: SchoolScript,
    *,
    base_url: str = "http://testserver",
    **settings_overrides,
) -> Harness:
    settings = Settings(app_secret="qa08-test-secret", **settings_overrides)
    app = create_app(settings)
    school = StubSchool(script)
    db_logins: list[str] = []

    async def stub_record_successful_login(factory, student_no: str) -> LoginDbResult:
        db_logins.append(student_no)
        return LoginDbResult(student_id=uuid.uuid4(), superseded_jobs=0)

    monkeypatch.setattr("app.api.auth.login_sso2", school)
    monkeypatch.setattr("app.api.auth.record_successful_login", stub_record_successful_login)
    client = TestClient(app, base_url=base_url)
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
    body = response.json()
    assert body["student_no"] == "M153000024"
    # todo 14 CSRF: the opaque token echoes in the body (cookie is httpOnly);
    # its set/rotate/flags semantics live in test_write_csrf.py.
    assert body["csrf_token"]
    cookie = response.headers["set-cookie"]
    # Transport rule (2026-08-28 Safari-over-http incident): `Secure` is
    # emitted only on HTTPS transports; HttpOnly/SameSite=lax/Path hold on
    # both. Default TestClient runs on http, so Secure must be absent here.
    for flag in ("session_id=", "HttpOnly", "SameSite=lax", "Path=/"):
        assert flag in cookie, cookie
    assert "Secure" not in _cookie_flags(cookie), cookie
    # adapter saw the RAW password exactly once, in memory only
    assert harness.school.calls == [("M153000024", TEST_PASSWORD)]

    sid = harness.session_id(response)
    assert harness.redis.remaining_ttl(f"site_session:{sid}") == 7 * 24 * 3600
    assert harness.redis.remaining_ttl(f"selcrs:{sid}") == 1800
    assert harness.redis.remaining_ttl(f"selcrs_hard:{sid}") == 7200
    assert TEST_COOKIE_VALUE in (harness.redis.peek(f"selcrs:{sid}") or "")
    assert harness.db_logins == ["M153000024"]  # upsert + supersede ran


# ---------- stu_enroll fan-out (M2: fail-soft, flag-gated) ----------


@dataclass
class StubFanout:
    """Scriptable stand-in for pipeline fanout_subsystem_logins."""

    result: FanoutResult
    calls: list[tuple[str, str]] = field(default_factory=list)

    async def __call__(self, student_no: str, password: str, **_kw: object) -> FanoutResult:
        self.calls.append((student_no, password))
        return self.result


def _fanout(*, regweb_ok: bool, sco_ok: bool, sco_err: LegError | None = None) -> FanoutResult:
    def _leg(ok: bool, err: LegError | None) -> FanoutLeg:
        jar = httpx.Cookies()
        if ok:
            jar.set("FAMILYJAR", "value")
        return FanoutLeg(available=ok, jar=jar if ok else None, error=err, attempts=1, elapsed_s=0.1)

    return FanoutResult(regweb=_leg(regweb_ok, None), sco=_leg(sco_ok, sco_err))


def test_login_with_flag_runs_fanout_and_parks_both_family_jars(monkeypatch, harness_factory):
    # Given flag ON and both subsystem legs succeeding
    harness = harness_factory(_succeed, feature_stu_enroll=True)
    stub = StubFanout(_fanout(regweb_ok=True, sco_ok=True))
    monkeypatch.setattr("app.api.auth.fanout_subsystem_logins", stub)

    # When the student logs in
    response = harness.login()

    # Then both availability flags ride the response and both jars park with
    # the same sliding/hard TTL contract as selcrs
    assert response.status_code == 200
    body = response.json()
    assert body["regweb_available"] is True
    assert body["sco_available"] is True
    sid = harness.session_id(response)
    assert harness.redis.peek(f"regweb:{sid}") == '[["FAMILYJAR", "value"]]'
    assert harness.redis.peek(f"stusco:{sid}") == '[["FAMILYJAR", "value"]]'
    assert harness.redis.remaining_ttl(f"regweb:{sid}") == 1800
    assert harness.redis.remaining_ttl(f"regweb_hard:{sid}") == 7200
    assert harness.redis.remaining_ttl(f"stusco:{sid}") == 1800
    assert stub.calls == [("M153000024", TEST_PASSWORD)]


def test_login_with_flag_off_skips_fanout_entirely(monkeypatch, harness_factory):
    # Given flag OFF (the default)
    harness = harness_factory(_succeed)
    stub = StubFanout(_fanout(regweb_ok=True, sco_ok=True))
    monkeypatch.setattr("app.api.auth.fanout_subsystem_logins", stub)

    # When the student logs in
    response = harness.login()

    # Then login behaves exactly as before: no fan-out call, no family keys,
    # flags explicitly False in the body
    assert response.status_code == 200
    assert response.json()["regweb_available"] is False
    assert response.json()["sco_available"] is False
    assert stub.calls == []
    assert harness.redis.keys_with_prefix("regweb") == []
    assert harness.redis.keys_with_prefix("stusco") == []


def test_login_fanout_partial_failure_stays_fail_soft_and_never_feeds_breaker(
    monkeypatch, harness_factory
):
    # Given flag ON with regweb green but sco dying by OUR captcha budget
    harness = harness_factory(_succeed, feature_stu_enroll=True)
    stub = StubFanout(_fanout(regweb_ok=True, sco_ok=False, sco_err=LegError.CAPTCHA_BUDGET))
    monkeypatch.setattr("app.api.auth.fanout_subsystem_logins", stub)

    # When the student logs in
    response = harness.login()

    # Then login still succeeds 200, flags split honestly, only the regweb jar
    # parks - and an OUR-side failure records NO breaker verdict at all
    assert response.status_code == 200
    body = response.json()
    assert body["regweb_available"] is True
    assert body["sco_available"] is False
    sid = harness.session_id(response)
    assert harness.redis.peek(f"regweb:{sid}") is not None
    assert harness.redis.peek(f"stusco:{sid}") is None
    assert harness.redis.peek("breaker:school:streak") is None


def test_login_fanout_school_unavailable_leg_feeds_the_breaker_once(
    monkeypatch, harness_factory
):
    # Given flag ON with the sco leg returning a SCHOOL verdict (drift)
    harness = harness_factory(_succeed, feature_stu_enroll=True)
    stub = StubFanout(
        _fanout(regweb_ok=True, sco_ok=False, sco_err=LegError.SCHOOL_UNAVAILABLE)
    )
    monkeypatch.setattr("app.api.auth.fanout_subsystem_logins", stub)

    # When the student logs in
    response = harness.login()

    # Then the exact-school-verdict rule fires once for that leg only
    assert response.status_code == 200
    assert response.json()["sco_available"] is False
    assert harness.redis.peek("breaker:school:streak") == "1"


def test_https_transport_pins_secure_on_login_and_logout_cookies(harness_factory):
    harness = harness_factory(_succeed, base_url="https://testserver")
    response = harness.login()
    assert response.status_code == 200
    for header in response.headers.get_list("set-cookie"):
        assert "Secure" in _cookie_flags(header), header
    sid = harness.session_id(response)

    out = harness.client.post("/api/auth/logout", cookies={"session_id": sid})
    assert out.status_code == 200
    for header in out.headers.get_list("set-cookie"):
        assert "Secure" in _cookie_flags(header), header


def test_http_transport_omits_secure_but_keeps_httponly_lax_on_logout(harness_factory):
    harness = harness_factory(_succeed)
    sid = harness.session_id(harness.login())

    out = harness.client.post("/api/auth/logout", cookies={"session_id": sid})
    assert out.status_code == 200
    for header in out.headers.get_list("set-cookie"):
        flags = _cookie_flags(header)
        assert "Secure" not in flags, header
        assert "HttpOnly" in flags and "SameSite=lax" in flags, header


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
    assert harness.redis.keys_with_prefix("selcrs") == []
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
    # Then: still 5 school calls, still 5 log entries (no append, no call);
    # the body carries the fixed lock window as the UI retry hint (todo 11).
    assert blocked.status_code == 429
    assert blocked.json()["detail"] == "too_many_attempts"
    assert blocked.json()["retry_after_minutes"] == 15
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
