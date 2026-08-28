"""Todo-17 QA driver: site-wide breaker evidence for qa/17-breaker.log.

Hermetic (real create_app + scripted login_sso2 + counting stubs for every
other school seam + FakeRedis; zero school contact happens anywhere). Proves
the todo-17 matrix: 5x UNKNOWN opens the breaker; login/stage/sync/preview
all refuse LOCALLY (503, zero outbound); /api/ops/state publishes the
degraded posture publicly and the internals only behind the admin gate;
recovery needs the wait + a coherent probe; a failed probe re-stamps the
wait, so only probe-alive success closes it.

Usage: cd backend && uv run python -m scripts.qa17_breaker
"""

import sys
import time
import uuid

import httpx
from fastapi.testclient import TestClient

import app.api.auth as auth_api
import app.api.selections as selections_api
import app.api.stage as stage_api
import app.api.write as write_api
from app.auth.breaker import OPENED_AT_KEY
from app.auth.students import LoginDbResult
from app.config import Settings
from app.main import create_app
from app.selcrs.endpoints import Sso2Result
from app.selcrs.errors import SelcrsUnavailable
from app.selcrs.sso2 import Sso2Outcome
from tests.fake_redis import FakeRedis

APP_SECRET = "qa17-breaker-secret"
PASSWORD = "QA17-mock-password"
STUDENT = "M153000024"
RECOVERY_AFTER = 300

failures = 0


def _verdict(ok: bool, label: str, detail: str = "") -> None:
    global failures
    failures += 0 if ok else 1
    print(f"[{'OK' if ok else 'FAIL'}] {label}" + (f" :: {detail}" if detail else ""))


class Rig:
    """One app instance + scriptable school + per-seam call counters."""

    def __init__(self) -> None:
        self.script = "success"
        self.school_calls = 0
        self.stage_calls = 0
        self.sync_calls = 0
        self.preview_probe_calls = 0

        async def stub_login(student_no: str, password: str) -> Sso2Result:
            self.school_calls += 1
            if self.script == "success":
                jar = httpx.Cookies()
                jar.set("ASPSESSIONIDQATEST", "QA17-mock-cookie")
                return Sso2Result(outcome=Sso2Outcome.SUCCESS, cookies=jar, detail=None)
            raise SelcrsUnavailable("scripted school timeout (qa17)")

        async def stub_db(factory, student_no: str) -> LoginDbResult:
            return LoginDbResult(student_id=uuid.uuid4(), superseded_jobs=0)

        async def stub_get_studfun(cookies=None, transport=None) -> str:
            self.stage_calls += 1
            raise AssertionError("get_studfun reached while proving zero school contact")

        async def stub_get_slt(cookies, transport=None) -> str:
            self.sync_calls += 1
            raise AssertionError("get_slt_result reached while proving zero school contact")

        async def stub_probe_stage():
            self.preview_probe_calls += 1
            raise AssertionError("probe_stage reached while proving zero school contact")

        app = create_app(Settings(app_secret=APP_SECRET))
        auth_api.login_sso2 = stub_login
        auth_api.record_successful_login = stub_db
        stage_api.get_studfun = stub_get_studfun
        selections_api.get_slt_result = stub_get_slt
        write_api.probe_stage = stub_probe_stage
        self.client = TestClient(app)
        self.client.__enter__()
        self.redis = FakeRedis()
        app.state.redis = self.redis

    def login(self) -> httpx.Response:
        return self.client.post(
            "/api/auth/login", json={"student_no": STUDENT, "password": PASSWORD}
        )

    def open_breaker(self) -> None:
        self.script = "unknown"
        statuses = [self.login().status_code for _ in range(5)]
        _verdict(
            statuses == [503] * 5 and self.redis.peek("breaker:school:opened_at") is not None,
            "5x UNKNOWN (timeout) -> 5x 503, breaker OPEN",
            f"statuses={statuses} streak={self.redis.peek('breaker:school:streak')}",
        )

    def backdate_open_stamp(self) -> None:
        """Simulated elapsed wait: what the clock reads RECOVERY_AFTER+1s later."""
        self.redis._values[OPENED_AT_KEY] = (repr(time.time() - RECOVERY_AFTER - 1), None)

    def close(self) -> None:
        self.client.__exit__(None, None, None)


def main() -> int:
    rig = Rig()
    try:
        # Given a working session (school healthy), then a timeout storm.
        login = rig.login()
        sid = next(
            part[len("session_id=") :]
            for part in login.headers["set-cookie"].split("; ")
            if part.startswith("session_id=")
        )
        csrf_token = login.json()["csrf_token"]
        _verdict(login.status_code == 200, "login SUCCESS (baseline, school healthy)")

        rig.open_breaker()
        calls_at_open = rig.school_calls

        # Public posture is honestly degraded; internals stay gated.
        public = rig.client.get("/api/ops/state").json()
        admin = rig.client.get(
            "/api/ops/state", headers={"X-App-Secret": APP_SECRET}
        ).json()
        _verdict(
            public["breaker"]["state"] == "open"
            and public["breaker"]["mode"] == "read-only"
            and public["breaker"]["streak"] is None
            and public["lockouts"] is None,
            "banner seam: /api/ops/state public shows open read-only, internals gate",
            f"public={public}",
        )
        _verdict(
            admin["breaker"]["streak"] == 5
            and admin["lockouts"] == {"today": 0, "yesterday": 0, "total": 0},
            "admin gate (X-App-Secret) reveals streak/thresholds/lockouts",
            f"admin={admin['breaker']['streak']} lockouts={admin['lockouts']['total']}",
        )

        # Every school-touching surface refuses LOCALLY: zero more calls.
        resp_login = rig.login()
        _verdict(
            resp_login.status_code == 503 and rig.school_calls == calls_at_open,
            "login -> LOCAL 503, ZERO outbound",
            f"body={resp_login.text} school_calls={rig.school_calls}",
        )
        resp_stage = rig.client.get("/api/stage", cookies={"session_id": sid})
        _verdict(
            resp_stage.status_code == 503 and rig.stage_calls == 0,
            "GET /api/stage -> LOCAL 503, zero Studfun calls",
            resp_stage.text,
        )
        resp_sync = rig.client.post("/api/me/selections/sync", cookies={"session_id": sid})
        _verdict(
            resp_sync.status_code == 503 and rig.sync_calls == 0,
            "POST /api/me/selections/sync -> LOCAL 503, zero slt_result calls",
            resp_sync.text,
        )
        resp_preview = rig.client.post(
            "/api/write/preview",
            json={"ops": [{"action": "-", "course_id": "DEADBEEF"}]},
            cookies={"session_id": sid, f"csrf_{sid}": csrf_token},
            headers={"X-CSRF-Token": csrf_token},
        )
        _verdict(
            resp_preview.status_code == 503 and rig.preview_probe_calls == 0,
            "POST /api/write/preview -> LOCAL 503, zero stage probes (write entrance hard-off)",
            resp_preview.text,
        )

        # Recovery: wait elapses (simulated) and the school answers coherently.
        rig.backdate_open_stamp()
        rig.script = "success"
        recovered = rig.login()
        state = rig.client.get("/api/ops/state").json()["breaker"]
        _verdict(
            recovered.status_code == 200
            and state["state"] == "closed"
            and state["mode"] == "normal"
            and rig.redis.peek("breaker:school:opened_at") is None,
            "recovery: elapsed wait + coherent probe -> breaker CLOSED",
            f"login={recovered.status_code} state={state['state']}",
        )

        # A failed probe re-stamps the wait (only consecutive success closes).
        rig.open_breaker()
        rig.backdate_open_stamp()
        rig.script = "unknown"
        before = rig.school_calls
        probe_fail = rig.login()
        _verdict(
            probe_fail.status_code == 503 and rig.school_calls == before + 1,
            "half-open probe FAILS (school still down): 503 via exactly one school call",
            f"school_calls={rig.school_calls}",
        )
        denied = rig.login()
        _verdict(
            denied.status_code == 503 and rig.school_calls == before + 1,
            "wait re-stamped: immediate retry refused LOCALLY (zero outbound)",
            f"school_calls={rig.school_calls}",
        )
        rig.backdate_open_stamp()
        rig.script = "success"
        final = rig.login()
        _verdict(
            final.status_code == 200
            and rig.client.get("/api/ops/state").json()["breaker"]["state"] == "closed",
            "probe-alive success after the wait -> CLOSED and serving",
        )
        return 1 if failures else 0
    finally:
        rig.close()


if __name__ == "__main__":
    sys.exit(main())
