"""Todo-8 QA driver: scripted mock-school auth flows for qa/08-*.log evidence.

Runs the REAL app (create_app) with two swaps: a scripted ``login_sso2``
stand-in (no school contact, all calls counted) and FakeRedis. Prints one
grep-friendly verdict line per step. Credentials here are test constants,
never real.

Usage: cd backend && uv run python -m scripts.qa08_mock_flows --scenario login|lockout|unknown
"""

import argparse
import sys
import uuid

import httpx
from fastapi.testclient import TestClient

import app.api.auth as auth_api
from app.auth.students import LoginDbResult
from app.config import Settings
from app.main import create_app
from app.selcrs.endpoints import Sso2Result
from app.selcrs.errors import SelcrsUnavailable
from app.selcrs.jar import deserialize_cookies
from app.selcrs.sso2 import FAILURE_MARKER, Sso2Outcome
from tests.fake_redis import FakeRedis

PASSWORD = "QA08-mock-password"
COOKIE_VALUE = "QA08-mock-cookie-value"
STUDENT = "M153000024"


def _script_success(student_no: str, password: str) -> Sso2Result:
    jar = httpx.Cookies()
    jar.set("ASPSESSIONIDQATEST", COOKIE_VALUE)
    return Sso2Result(outcome=Sso2Outcome.SUCCESS, cookies=jar, detail=None)


def _script_credential_fail(student_no: str, password: str) -> Sso2Result:
    return Sso2Result(
        outcome=Sso2Outcome.CREDENTIAL_FAIL, cookies=httpx.Cookies(), detail=FAILURE_MARKER
    )


def _script_unknown(student_no: str, password: str) -> Sso2Result:
    raise SelcrsUnavailable("scripted UNKNOWN school behaviour")


class Rig:
    def __init__(self, script) -> None:
        self.calls: list[tuple[str, str]] = []

        async def stub_login(student_no: str, password: str) -> Sso2Result:
            self.calls.append((student_no, password))
            return script(student_no, password)

        async def stub_db(factory, student_no: str) -> LoginDbResult:
            return LoginDbResult(student_id=uuid.uuid4(), superseded_jobs=0)

        app = create_app(Settings(app_secret="qa08-mock-secret"))
        auth_api.login_sso2 = stub_login
        auth_api.record_successful_login = stub_db
        self.client = TestClient(app)
        self.client.__enter__()
        self.redis = FakeRedis()
        app.state.redis = self.redis

    def login(self, student_no: str = STUDENT) -> httpx.Response:
        return self.client.post(
            "/api/auth/login", json={"student_no": student_no, "password": PASSWORD}
        )

    def close(self) -> None:
        self.client.__exit__(None, None, None)


def _verdict(ok: bool, label: str, detail: str = "") -> None:
    print(f"[{'OK' if ok else 'FAIL'}] {label}" + (f" :: {detail}" if detail else ""))


def scenario_login() -> int:
    rig = Rig(_script_success)
    try:
        response = rig.login()
        _verdict(response.status_code == 200, "login SUCCESS -> 200", response.text)
        cookie = response.headers.get("set-cookie", "")
        _verdict(
            all(flag in cookie for flag in ("session_id=", "HttpOnly", "Secure", "SameSite=lax")),
            "Set-Cookie flags httpOnly+Secure+SameSite=Lax",
            cookie.replace(rig.redis.keys_with_prefix("site_session:")[0].split(":")[1], "<sid>")
            if rig.redis.keys_with_prefix("site_session:")
            else cookie,
        )
        sid = next(
            part.split("=", 1)[1] for part in cookie.split("; ") if part.startswith("session_id=")
        )
        jar_raw = rig.redis.peek(f"selcrs:{sid}") or ""
        jar = deserialize_cookies(jar_raw)
        _verdict(
            jar.get("ASPSESSIONIDQATEST") == COOKIE_VALUE
            and rig.redis.remaining_ttl(f"selcrs:{sid}") == 1800
            and rig.redis.remaining_ttl(f"selcrs_hard:{sid}") == 7200
            and rig.redis.remaining_ttl(f"site_session:{sid}") == 7 * 24 * 3600,
            f"selcrs parked Redis-only (SLIDING=1800 / HARD=7200; site session 7d): {jar_raw}",
        )
        me = rig.client.get("/api/auth/me", cookies={"session_id": sid})
        _verdict(me.status_code == 200 and me.json() == {"student_no": STUDENT}, "me -> 200", me.text)
        out = rig.client.post("/api/auth/logout", cookies={"session_id": sid})
        gone = rig.client.get("/api/auth/me", cookies={"session_id": sid})
        _verdict(
            out.status_code == 200
            and gone.status_code == 401
            and rig.redis.peek(f"selcrs:{sid}") is None
            and rig.redis.peek(f"site_session:{sid}") is None,
            "logout clears site session + selcrs; me -> 401",
            f"me-after-logout={gone.status_code} redis-empty={rig.redis.keys_with_prefix('selcrs') == []}",
        )
        return 0
    finally:
        rig.close()


def scenario_lockout() -> int:
    rig = Rig(_script_credential_fail)
    try:
        statuses = [rig.login().status_code for _ in range(5)]
        _verdict(statuses == [401] * 5, "5x CREDENTIAL-FAIL -> 5x 401", str(statuses))
        locked = rig.redis.keys_with_prefix(f"loginlock:{STUDENT}")
        _verdict(bool(locked), "fixed 15-min lock engaged after 5th failure", str(locked))
        blocked = rig.login()
        _verdict(
            blocked.status_code == 429
            and len(rig.calls) == 5
            and rig.redis.zcount_peek(f"loginfail:{STUDENT}") == 5,
            "locked attempt -> local 429, NOT a school call, NOT appended to the log",
            f"status={blocked.status_code} school_calls={len(rig.calls)} log_entries={rig.redis.zcount_peek(f'loginfail:{STUDENT}')}",
        )
        rig2 = Rig(_script_unknown)
        try:
            resp = rig2.login(student_no="M153000099")
            _verdict(
                resp.status_code == 503
                and rig2.redis.zcount_peek("loginfail:M153000099") == 0
                and rig2.redis.peek("breaker:school:streak") == "1"
                and rig2.redis.peek("loginlock:M153000099") is None,
                "UNKNOWN -> 503, breaker streak +1, NEVER the account lockout",
                f"status={resp.status_code} streak={rig2.redis.peek('breaker:school:streak')}",
            )
        finally:
            rig2.close()
        return 0
    finally:
        rig.close()


def scenario_unknown() -> int:
    rig = Rig(_script_unknown)
    try:
        statuses = [rig.login().status_code for _ in range(5)]
        _verdict(
            statuses == [503] * 5 and len(rig.calls) == 5,
            "5x UNKNOWN -> 5x 503, 5 school calls, streak=5 -> breaker OPENS",
            f"statuses={statuses} streak={rig.redis.peek('breaker:school:streak')}",
        )
        for attempt in range(3):
            resp = rig.login()
            _verdict(
                resp.status_code == 503 and len(rig.calls) == 5,
                f"breaker-open attempt {attempt + 1} -> LOCAL 503, school_calls still {len(rig.calls)} (ZERO outbound)",
                resp.text,
            )
        _verdict(
            rig.redis.keys_with_prefix("loginfail:") == [],
            "no account lockout recorded through any of this",
        )
        return 0
    finally:
        rig.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=("login", "lockout", "unknown"), required=True)
    args = parser.parse_args()
    return {"login": scenario_login, "lockout": scenario_lockout, "unknown": scenario_unknown}[
        args.scenario
    ]()


if __name__ == "__main__":
    sys.exit(main())
