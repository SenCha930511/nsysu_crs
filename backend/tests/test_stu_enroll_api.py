"""stu_enroll /api/me/* endpoint contract tests (plan §5.5 / M2).

Fully hermetic, patterned on test_selections_api.py: the school's relay chain
is a scripted ``open_relay`` stub (monkeypatched at app.api.stu_enroll), Redis
is FakeRedis, and sessions are seeded directly via create_site_session +
store_regweb - no password exists here. Fixture bytes: tfstudata's masked
115-1 page for the parser; synthetic %PDF bytes for the cert passthrough.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.auth.breaker import build_breaker
from app.auth.sessions import create_site_session, store_regweb
from app.config import Settings
from app.main import create_app
from app.selcrs.errors import SelcrsSessionExpired, SelcrsUnavailable
from app.stuenroll.handoff import ChainResult
from tests.fake_redis import FakeRedis

FIXTURES = Path(__file__).parent / "fixtures"
PAYMENT_PAGE = (FIXTURES / "stuenroll_payment_live_1151.html").read_bytes()
PDF_BYTES = b"%PDF-1.4 synthetic-cert-bytes-m2"
PAYMENT_PATH = "/api/me/payment-status"
CERT_PATH = "/api/me/enrollment-cert"

RelayScript = Callable[[str], ChainResult]


def _landing(content: bytes, content_type: str) -> ChainResult:
    return ChainResult(
        status_code=200,
        content=content,
        content_type=content_type,
        url="https://scripted/landing",
        hops=1,
        redirects=0,
        cookies=httpx.Cookies(),
    )


def _payment_page(_url: str) -> ChainResult:
    return _landing(PAYMENT_PAGE, "text/html; charset=utf-8")


def _pdf(_url: str) -> ChainResult:
    return _landing(PDF_BYTES, "application/pdf")


def _html_not_pdf(_url: str) -> ChainResult:
    return _landing(b"<html>not a pdf</html>", "text/html; charset=utf-8")


def _bounce(_url: str) -> ChainResult:
    raise SelcrsSessionExpired("scripted relay bounce")


def _unknown(_url: str) -> ChainResult:
    raise SelcrsUnavailable("scripted unknown school shape")


@dataclass
class StubRelay:
    """Scriptable stand-in for stuenroll's open_relay; records every call."""

    script: RelayScript
    calls: list[str] = field(default_factory=list)

    async def __call__(
        self,
        start_url: str,
        jar: httpx.Cookies | None,
        *,
        transport: object | None = None,
    ) -> ChainResult:
        self.calls.append(start_url)
        return self.script(start_url)


@dataclass
class Harness:
    client: TestClient
    redis: FakeRedis
    settings: Settings
    relay: StubRelay

    async def seed_session(self, *, with_jar: bool = True) -> str:
        """A live site session (with a parked regweb jar unless told otherwise)."""
        session_id = await create_site_session(self.redis, "M153000024")
        if with_jar:
            await store_regweb(
                self.redis,
                session_id,
                '[["ASPSESSIONIDX", "stubvalue"]]',
                sliding_ttl=1800,
                hard_ttl=7200,
            )
        return session_id


def _make_harness(monkeypatch, script: RelayScript, *, flag: bool = True) -> Harness:
    settings = Settings(app_secret="stu-enroll-contract-secret", feature_stu_enroll=flag)
    app = create_app(settings)
    relay = StubRelay(script)
    monkeypatch.setattr("app.api.stu_enroll.open_relay", relay)
    client = TestClient(app)
    client.__enter__()
    harness = Harness(client=client, redis=FakeRedis(), settings=settings, relay=relay)
    client.app.state.redis = harness.redis
    return harness


@pytest.fixture
def harness_factory(monkeypatch):
    built: list[Harness] = []

    def factory(script: RelayScript, **kwargs) -> Harness:
        harness = _make_harness(monkeypatch, script, **kwargs)
        built.append(harness)
        return harness

    yield factory
    for harness in built:
        harness.client.__exit__(None, None, None)


@pytest.mark.anyio
@pytest.mark.parametrize("path", [PAYMENT_PATH, CERT_PATH])
async def test_flag_off_gives_404_and_never_touches_the_school(harness_factory, path):
    # Given the feature flag OFF and an otherwise-valid session + jar
    harness = harness_factory(_payment_page, flag=False)
    sid = await harness.seed_session()

    # When either endpoint is hit
    response = harness.client.get(path, cookies={"session_id": sid})

    # Then the non-public 404 rule answers and the relay never fires
    assert response.status_code == 404
    assert response.json()["detail"] == "not_found"
    assert harness.relay.calls == []


@pytest.mark.anyio
@pytest.mark.parametrize("path", [PAYMENT_PATH, CERT_PATH])
async def test_anonymous_gets_401(harness_factory, path):
    harness = harness_factory(_payment_page)
    response = harness.client.get(path)
    assert response.status_code == 401
    assert response.json()["detail"] == "not_authenticated"


@pytest.mark.anyio
@pytest.mark.parametrize("path", [PAYMENT_PATH, CERT_PATH])
async def test_missing_regweb_jar_gives_family_expired(harness_factory, path):
    harness = harness_factory(_payment_page)
    sid = await harness.seed_session(with_jar=False)

    response = harness.client.get(path, cookies={"session_id": sid})
    assert response.status_code == 401
    assert response.json()["detail"] == "REGWEB_EXPIRED"
    assert harness.relay.calls == []


@pytest.mark.anyio
@pytest.mark.parametrize("path", [PAYMENT_PATH, CERT_PATH])
async def test_open_breaker_answers_503_with_zero_school_contact(harness_factory, path):
    harness = harness_factory(_payment_page)
    sid = await harness.seed_session()
    breaker = build_breaker(harness.redis, harness.settings)
    for _ in range(harness.settings.breaker_failure_threshold):
        await breaker.record_unknown()

    response = harness.client.get(path, cookies={"session_id": sid})
    assert response.status_code == 503
    assert response.json()["detail"] == "school_unavailable"
    assert harness.relay.calls == []


@pytest.mark.anyio
@pytest.mark.parametrize("path", [PAYMENT_PATH, CERT_PATH])
async def test_relay_bounce_gives_family_expired(harness_factory, path):
    harness = harness_factory(_bounce)
    sid = await harness.seed_session()

    response = harness.client.get(path, cookies={"session_id": sid})
    assert response.status_code == 401
    assert response.json()["detail"] == "REGWEB_EXPIRED"
    assert len(harness.relay.calls) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("path", [PAYMENT_PATH, CERT_PATH])
async def test_unrecognized_school_behaviour_gives_503(harness_factory, path):
    harness = harness_factory(_unknown)
    sid = await harness.seed_session()

    response = harness.client.get(path, cookies={"session_id": sid})
    assert response.status_code == 503
    assert response.json()["detail"] == "school_unavailable"


@pytest.mark.anyio
async def test_payment_happy_path_normalizes_the_masked_1151_page(harness_factory):
    # Given a live session and the school landing on the REAL masked page
    harness = harness_factory(_payment_page)
    sid = await harness.seed_session()

    # When payment status is fetched
    response = harness.client.get(PAYMENT_PATH, cookies={"session_id": sid})

    # Then the bills come back normalized, with no school-internal id leaked
    assert response.status_code == 200
    body = response.json()
    assert body["dept"] == "資訊工程學系碩士班"
    assert len(body["bills"]) == 1
    bill = body["bills"][0]
    assert bill["item"] == "1151學雜費"
    assert bill["amount"].startswith("14,155")
    assert bill["status"] == "繳費成功"
    assert bill["pay_date"] == "2026/08/31"
    assert bill["receipt_available"] is True
    assert "IM1151006292" not in response.text  # mst_sno stays server-side


@pytest.mark.anyio
async def test_cert_passthrough_streams_pdf_with_no_store_headers(harness_factory):
    harness = harness_factory(_pdf)
    sid = await harness.seed_session()

    response = harness.client.get(CERT_PATH, cookies={"session_id": sid})

    assert response.status_code == 200
    assert response.content == PDF_BYTES
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-disposition"].startswith("attachment")
