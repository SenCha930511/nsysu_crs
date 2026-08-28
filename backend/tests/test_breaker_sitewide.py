"""Site-wide breaker posture (plan todo 17; QA qa/17-breaker.log).

The todo-8 breaker guarded login; todo 17 extends the same streak/open state
to EVERY school-touching API surface (stage probe, selections sync, write
preview entrance — /api/write/submit was already wired in todo 15). While
open, all of them answer 503 LOCALLY with zero school contact; catalog/meta
reads stay up (full degraded read-only). Recovery rides the todo-8 semantics:
after BREAKER_RECOVERY_AFTER one half-open probe is admitted; a coherent
answer closes everything; a failed probe re-stamps the wait — so only
consecutive probe-alive successes ever close the breaker.

Hermetic: scripted login_sso2 + counting stubs for the school adapters,
FakeRedis, no Postgres. The simulated wait is an honest direct write of the
opened_at stamp into the fake - that is what the clock would read after
BREAKER_RECOVERY_AFTER seconds.
"""

import time
import uuid
from dataclasses import dataclass, field

import httpx
import pytest
from fastapi.exceptions import HTTPException
from fastapi.testclient import TestClient

from app.auth.breaker import OPENED_AT_KEY, STREAK_KEY
from app.auth.students import LoginDbResult
from app.config import Settings
from app.main import create_app
from app.selcrs.endpoints import Sso2Result
from app.selcrs.errors import SelcrsUnavailable
from app.selcrs.sso2 import Sso2Outcome
from tests.fake_redis import FakeRedis

TEST_PASSWORD = "Br17-TestPw-31z!"
TEST_COOKIE_VALUE = "QA17-BREAKER-COOKIE-VALUE"
STUDENT = "M153000024"
RECOVERY_AFTER = 300


def _succeed(student_no: str, password: str) -> Sso2Result:
    jar = httpx.Cookies()
    jar.set("ASPSESSIONIDQATEST", TEST_COOKIE_VALUE)
    return Sso2Result(outcome=Sso2Outcome.SUCCESS, cookies=jar, detail=None)


def _unknown(student_no: str, password: str) -> Sso2Result:
    raise SelcrsUnavailable("scripted school timeout (qa17 breaker evidence)")


@dataclass
class Harness:
    client: TestClient
    redis: FakeRedis
    script: list  # single-element box: the swappable login script
    login_calls: list[tuple[str, str]] = field(default_factory=list)
    stage_calls: int = 0
    sync_calls: int = 0
    preview_probe_calls: int = 0

    def login(self, student_no: str = STUDENT) -> httpx.Response:
        return self.client.post(
            "/api/auth/login", json={"student_no": student_no, "password": TEST_PASSWORD}
        )

    @staticmethod
    def _session_id(response: httpx.Response) -> str:
        cookie = response.headers["set-cookie"]
        return next(
            part[len("session_id=") :] for part in cookie.split("; ") if part.startswith("session_id=")
        )

    def login_and_keep_session(self) -> tuple[str, str]:
        """A working session: returns (session_id, csrf_token)."""
        response = self.login()
        assert response.status_code == 200, response.text
        return self._session_id(response), response.json()["csrf_token"]

    def open_breaker(self) -> None:
        self.script[0] = _unknown
        for _ in range(5):
            assert self.login().status_code == 503

    def backdate_open_stamp(self, seconds: float = RECOVERY_AFTER + 1) -> None:
        """Simulated elapsed wait: what the clock reads recovery_after later."""
        self.redis._values[OPENED_AT_KEY] = (repr(time.time() - seconds), None)


@pytest.fixture
def harness(monkeypatch):
    settings = Settings(app_secret="qa17-breaker-secret")
    app = create_app(settings)
    script: list = [_succeed]
    box = Harness(client=None, redis=FakeRedis(), script=script)  # type: ignore[arg-type]

    async def stub_login(student_no: str, password: str) -> Sso2Result:
        box.login_calls.append((student_no, password))
        return script[0](student_no, password)

    async def stub_db(factory, student_no: str) -> LoginDbResult:
        return LoginDbResult(student_id=uuid.uuid4(), superseded_jobs=0)

    async def stub_get_studfun(cookies=None, transport=None) -> str:
        box.stage_calls += 1
        raise AssertionError("stage stub must never be reached in these tests")

    async def stub_get_slt(cookies, transport=None) -> str:
        box.sync_calls += 1
        raise AssertionError("selections stub must never be reached in these tests")

    async def stub_probe_stage(cookies):
        box.preview_probe_calls += 1
        raise AssertionError("preview probe stub must never be reached in these tests")

    monkeypatch.setattr("app.api.auth.login_sso2", stub_login)
    monkeypatch.setattr("app.api.auth.record_successful_login", stub_db)
    monkeypatch.setattr("app.api.stage.get_studfun", stub_get_studfun)
    monkeypatch.setattr("app.api.selections.get_slt_result", stub_get_slt)
    client = TestClient(app)
    client.__enter__()
    box.client = client
    client.app.state.redis = box.redis
    yield box
    client.__exit__(None, None, None)


def test_open_refuses_everything_school_touching_then_recovers(harness):
    # Given a working session, then five straight transport failures
    sid, csrf_token = harness.login_and_keep_session()
    session_cookies = {"session_id": sid}
    harness.open_breaker()
    school_calls_after_open = len(harness.login_calls)
    assert harness.redis.peek(OPENED_AT_KEY) is not None

    # When anything school-touching is attempted, it is refused LOCALLY
    assert harness.login().status_code == 503
    assert len(harness.login_calls) == school_calls_after_open  # zero outbound

    stage = harness.client.get("/api/stage", cookies=session_cookies)
    assert stage.status_code == 503 and stage.json() == {"detail": "school_unavailable"}

    sync = harness.client.post("/api/me/selections/sync", cookies=session_cookies)
    assert sync.status_code == 503 and sync.json() == {"detail": "school_unavailable"}

    preview = harness.client.post(
        "/api/write/preview",
        json={"ops": [{"action": "-", "course_id": "DEADBEEF"}]},
        cookies={**session_cookies, f"csrf_{sid}": csrf_token},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert preview.status_code == 503 and preview.json() == {"detail": "school_unavailable"}

    # Then ZERO adapter/probe calls fired anywhere
    assert (harness.stage_calls, harness.sync_calls, harness.preview_probe_calls) == (0, 0, 0)

    # But the degraded state is honestly visible for the SPA banner
    state = harness.client.get("/api/ops/state")
    assert state.status_code == 200
    assert state.json()["breaker"]["state"] == "open"
    assert state.json()["breaker"]["mode"] == "read-only"

    # When the recovery wait elapses and the school answers coherently again
    harness.backdate_open_stamp()
    harness.script[0] = _succeed
    assert harness.login().status_code == 200  # the admitted probe closes it

    # Then the site is fully back: state clean, login served normally
    assert harness.redis.peek(OPENED_AT_KEY) is None
    assert harness.redis.peek(STREAK_KEY) is None
    assert harness.client.get("/api/ops/state").json()["breaker"]["state"] == "closed"
    assert harness.client.get("/api/ops/state").json()["breaker"]["mode"] == "normal"


def test_failed_probe_restamps_the_wait(harness):
    # Given an open breaker whose wait has elapsed
    harness.login_and_keep_session()
    harness.open_breaker()
    harness.backdate_open_stamp()

    # When the admitted probe also fails (school still timing out)
    harness.script[0] = _unknown
    assert harness.login().status_code == 503
    probe_calls = len(harness.login_calls)

    # Then the open stamp re-armed: immediate callers are refused LOCALLY again
    assert harness.login().status_code == 503
    assert len(harness.login_calls) == probe_calls


def test_preview_probe_outcomes_feed_and_close_the_breaker(harness, monkeypatch):
    # Given a session and a streak of 4 (one below threshold)
    sid, csrf_token = harness.login_and_keep_session()
    harness.redis._values[STREAK_KEY] = ("4", None)

    # When the preview's fresh school probe dies (write-probe 503 contract)
    async def failing_probe(cookies):
        harness.preview_probe_calls += 1
        raise HTTPException(status_code=503, detail="school_unavailable")

    monkeypatch.setattr("app.api.write.probe_stage", failing_probe)
    response = harness.client.post(
        "/api/write/preview",
        json={"ops": [{"action": "-", "course_id": "DEADBEEF"}]},
        cookies={"session_id": sid, f"csrf_{sid}": csrf_token},
        headers={"X-CSRF-Token": csrf_token},
    )

    # Then the failure fed the streak past threshold: the breaker opens
    assert response.status_code == 503
    assert harness.preview_probe_calls == 1
    assert harness.redis.peek(STREAK_KEY) == "5"
    assert harness.redis.peek(OPENED_AT_KEY) is not None
    # ...and subsequent login is refused locally (write + login entrances agree)
    assert harness.login().status_code == 503
    login_calls_before = len(harness.login_calls)
    assert harness.login().status_code == 503
    assert len(harness.login_calls) == login_calls_before
