"""Request access log (plan todo 17): JSON-ish lines + request-id, zero secret bytes.

The grep test below is the load-bearing one: login + a query string full of
sentries run end to end, and the captured access records carry neither the
password (raw/transformed), any cookie value, the session id, nor query
params - only ts/request_id/method/path/status/latency_ms.
"""

import json
import logging
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from app.auth.students import LoginDbResult
from app.config import Settings
from app.main import create_app
from app.request_log import ACCESS_LOGGER, REQUEST_ID_HEADER
from app.selcrs.endpoints import Sso2Result
from app.selcrs.sso2 import Sso2Outcome
from app.selcrs.transform import base64md5
from tests.fake_redis import FakeRedis

SENTINEL_PASSWORD = "Log17-Sentry!rare-string-8842"
SENTINEL_COOKIE = "QA17-LOG-COOKIE-cc31f0"
SENTINEL_QUERY = "sentry-query-must-not-appear-9917"


def _access_lines(caplog) -> list[dict]:
    lines = []
    for record in caplog.records:
        if record.name == ACCESS_LOGGER:
            lines.append(json.loads(record.getMessage()))
    return lines


def test_access_logger_has_a_real_handler_outside_pytest(rig):
    """create_app wires a StreamHandler: bare uvicorn drops unhandled INFO records."""
    access_logger = logging.getLogger(ACCESS_LOGGER)
    assert any(isinstance(handler, logging.StreamHandler) for handler in access_logger.handlers)
    assert access_logger.level == logging.INFO


@pytest.fixture
def rig(monkeypatch):
    def succeed(student_no: str, password: str) -> Sso2Result:
        jar = httpx.Cookies()
        jar.set("ASPSESSIONIDQATEST", SENTINEL_COOKIE)
        return Sso2Result(outcome=Sso2Outcome.SUCCESS, cookies=jar, detail=None)

    async def stub_login(student_no: str, password: str) -> Sso2Result:
        return succeed(student_no, password)

    async def stub_db(factory, student_no: str) -> LoginDbResult:
        return LoginDbResult(student_id=uuid.uuid4(), superseded_jobs=0)

    monkeypatch.setattr("app.api.auth.login_sso2", stub_login)
    monkeypatch.setattr("app.api.auth.record_successful_login", stub_db)
    app = create_app(Settings(app_secret="qa17-log-secret"))
    client = TestClient(app)
    client.__enter__()
    client.app.state.redis = FakeRedis()
    yield client
    client.__exit__(None, None, None)


def test_access_line_shape_and_request_id_roundtrip(rig, caplog):
    with caplog.at_level(logging.INFO, logger=ACCESS_LOGGER):
        login = rig.post(
            "/api/auth/login",
            json={"student_no": "M153000024", "password": SENTINEL_PASSWORD},
            headers={REQUEST_ID_HEADER: "qa17-req-fixed-1"},
        )
        rig.get("/api/does-not-exist", params={"pw": SENTINEL_QUERY})

    # Given/when above: then the login round trip logged exactly our shape
    assert login.status_code == 200
    assert login.headers[REQUEST_ID_HEADER] == "qa17-req-fixed-1"

    lines = _access_lines(caplog)
    assert [line["path"] for line in lines] == ["/api/auth/login", "/api/does-not-exist"]
    login_line, missing_line = lines
    for line in lines:
        assert set(line) == {"ts", "request_id", "method", "path", "status", "latency_ms"}
        assert isinstance(line["latency_ms"], float)
        assert isinstance(line["ts"], str)
    assert (login_line["method"], login_line["status"]) == ("POST", 200)
    assert login_line["request_id"] == "qa17-req-fixed-1"
    assert (missing_line["method"], missing_line["status"]) == ("GET", 404)


def test_no_body_cookie_or_query_bytes_ever_logged(rig, caplog):
    transformed = base64md5(SENTINEL_PASSWORD)
    with caplog.at_level(logging.DEBUG):
        login = rig.post(
            "/api/auth/login",
            json={"student_no": "M153000024", "password": SENTINEL_PASSWORD},
        )
        session_id = next(
            part[len("session_id=") :]
            for part in login.headers["set-cookie"].split("; ")
            if part.startswith("session_id=")
        )
        rig.get("/api/does-not-exist", params={"leak": SENTINEL_QUERY})
        lines = _access_lines(caplog)

    assert lines, "the outermost middleware must log even unhandled paths"
    blob = "\n".join(json.dumps(line) for line in lines)
    for secret in (SENTINEL_PASSWORD, transformed, SENTINEL_COOKIE, session_id, SENTINEL_QUERY):
        assert secret not in blob
    # minted request-ids are fresh opaque values, and the response echoes them
    assert lines[0]["request_id"] != session_id
    assert rig_response_id(rig) is not None


def rig_response_id(client: TestClient) -> str | None:
    return client.get("/api/ops/state").headers.get(REQUEST_ID_HEADER)
