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
from app.auth.sessions import create_site_session, store_regweb, store_stusco
from app.config import Settings
from app.main import create_app
from app.selcrs.errors import SelcrsSessionExpired, SelcrsUnavailable
from app.stuenroll.endpoints import (
    CHECKLIST_RELAY_URL,
    RECEIPT_RELAY_PREFIX,
    TFSTU_RELAY_URL,
)
from app.stuenroll.handoff import ChainResult
from app.stuenroll.parse import PaymentPage
from tests.fake_redis import FakeRedis

FIXTURES = Path(__file__).parent / "fixtures"
PAYMENT_PAGE = (FIXTURES / "stuenroll_payment_live_1151.html").read_bytes()
PDF_BYTES = b"%PDF-1.4 synthetic-cert-bytes-m2"
PAYMENT_PATH = "/api/me/payment-status"
CERT_PATH = "/api/me/enrollment-cert"
CHECKLIST_PATH = "/api/me/registration-checklist"
RECEIPT_PATH = "/api/me/payment-receipt"
CHECKLIST_PAGE = (FIXTURES / "stuenroll_regweb_main_live_1151.html").read_bytes()

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


def _checklist_page(_url: str) -> ChainResult:
    return _landing(CHECKLIST_PAGE, "text/html; charset=utf-8")


def _payment_then_receipt_pdf(url: str) -> ChainResult:
    # Two-hop dispatch: bills page on the receipt-envelope hop, PDF on the
    # receipt href (contains 'tfstudata.asp').
    if "tfstudata.asp" in url:
        return _landing(PDF_BYTES, "application/pdf")
    return _landing(PAYMENT_PAGE, "text/html; charset=utf-8")


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

    async def seed_session(self, *, with_jar: bool = True, family: str = "regweb") -> str:
        """A live site session (with a parked jar for the given family if asked)."""
        session_id = await create_site_session(self.redis, "M153000024")
        if with_jar:
            store = store_regweb if family == "regweb" else store_stusco
            await store(
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
@pytest.mark.parametrize("path", [PAYMENT_PATH, CERT_PATH, CHECKLIST_PATH, RECEIPT_PATH])
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
@pytest.mark.parametrize("path", [PAYMENT_PATH, CERT_PATH, CHECKLIST_PATH, RECEIPT_PATH])
async def test_anonymous_gets_401(harness_factory, path):
    harness = harness_factory(_payment_page)
    response = harness.client.get(path)
    assert response.status_code == 401
    assert response.json()["detail"] == "not_authenticated"


@pytest.mark.anyio
@pytest.mark.parametrize("path", [PAYMENT_PATH, CERT_PATH, CHECKLIST_PATH, RECEIPT_PATH])
async def test_missing_regweb_jar_gives_family_expired(harness_factory, path):
    harness = harness_factory(_payment_page)
    sid = await harness.seed_session(with_jar=False)

    response = harness.client.get(path, cookies={"session_id": sid})
    assert response.status_code == 401
    assert response.json()["detail"] == "REGWEB_EXPIRED"
    assert harness.relay.calls == []


@pytest.mark.anyio
@pytest.mark.parametrize("path", [PAYMENT_PATH, CERT_PATH, CHECKLIST_PATH, RECEIPT_PATH])
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
@pytest.mark.parametrize("path", [PAYMENT_PATH, CERT_PATH, CHECKLIST_PATH, RECEIPT_PATH])
async def test_relay_bounce_gives_family_expired(harness_factory, path):
    harness = harness_factory(_bounce)
    sid = await harness.seed_session()

    response = harness.client.get(path, cookies={"session_id": sid})
    assert response.status_code == 401
    assert response.json()["detail"] == "REGWEB_EXPIRED"
    assert len(harness.relay.calls) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("path", [PAYMENT_PATH, CERT_PATH, CHECKLIST_PATH, RECEIPT_PATH])
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


GRADES_PATH = "/api/me/grades"
GRADES_SYNC_PATH = "/api/me/grades/sync"
HISTORY_SHELL = (FIXTURES / "stuenroll_grades_history_live_1151.html").read_bytes()
RPT_WITH_ROWS = """<html><head><title>國立中山大學 成績查詢</title>
<link rel="stylesheet" href="include/css/sco_qry_rpt.css" /></head><body><center>
<table><tr><th>課號</th><th>科目名稱</th><th>學分</th><th>成績</th></tr>
<tr><td>M5001</td><td>高等演算法</td><td>3</td><td>95</td></tr>
<tr><td>M5002</td><td>高等資料庫</td><td>3</td><td>88</td></tr></table>
</center></body></html>""".encode()


def _history_shell(_url: str) -> ChainResult:
    return _landing(HISTORY_SHELL, "text/html; charset=utf-8")


def _rpt_with_rows(_url: str) -> ChainResult:
    return _landing(RPT_WITH_ROWS, "text/html; charset=utf-8")


@pytest.mark.anyio
@pytest.mark.parametrize("method,path", [("get", GRADES_PATH), ("post", GRADES_SYNC_PATH)])
async def test_grades_flag_off_gives_404_with_zero_school_contact(harness_factory, method, path):
    harness = harness_factory(_history_shell, flag=False)
    sid = await harness.seed_session(family="stusco")

    response = getattr(harness.client, method)(path, cookies={"session_id": sid})
    assert response.status_code == 404
    assert response.json()["detail"] == "not_found"
    assert harness.relay.calls == []


@pytest.mark.anyio
async def test_grades_get_is_empty_before_first_sync(harness_factory):
    harness = harness_factory(_history_shell)
    sid = await harness.seed_session(family="stusco")

    response = harness.client.get(GRADES_PATH, cookies={"session_id": sid})
    assert response.status_code == 200
    assert response.json() == {"synced_at": None, "items": []}
    assert harness.relay.calls == []  # reads never touch the school


@pytest.mark.anyio
async def test_grades_sync_anonymous_gets_401(harness_factory):
    harness = harness_factory(_history_shell)
    response = harness.client.post(GRADES_SYNC_PATH)
    assert response.status_code == 401
    assert response.json()["detail"] == "not_authenticated"


@pytest.mark.anyio
async def test_grades_sync_missing_stusco_jar_gives_family_expired(harness_factory):
    harness = harness_factory(_history_shell)
    sid = await harness.seed_session(with_jar=False)

    response = harness.client.post(GRADES_SYNC_PATH, cookies={"session_id": sid})
    assert response.status_code == 401
    assert response.json()["detail"] == "SCO_EXPIRED"
    assert harness.relay.calls == []


@pytest.mark.anyio
async def test_grades_sync_open_breaker_answers_503_without_school_contact(harness_factory):
    harness = harness_factory(_history_shell)
    sid = await harness.seed_session(family="stusco")
    breaker = build_breaker(harness.redis, harness.settings)
    for _ in range(harness.settings.breaker_failure_threshold):
        await breaker.record_unknown()

    response = harness.client.post(GRADES_SYNC_PATH, cookies={"session_id": sid})
    assert response.status_code == 503
    assert response.json()["detail"] == "school_unavailable"
    assert harness.relay.calls == []


@pytest.mark.anyio
async def test_grades_sync_relay_bounce_gives_family_expired(harness_factory):
    harness = harness_factory(_bounce)
    sid = await harness.seed_session(family="stusco")

    response = harness.client.post(GRADES_SYNC_PATH, cookies={"session_id": sid})
    assert response.status_code == 401
    assert response.json()["detail"] == "SCO_EXPIRED"


@pytest.mark.anyio
async def test_grades_sync_unrecognized_school_behaviour_gives_503(harness_factory):
    harness = harness_factory(_unknown)
    sid = await harness.seed_session(family="stusco")

    response = harness.client.post(GRADES_SYNC_PATH, cookies={"session_id": sid})
    assert response.status_code == 503
    assert response.json()["detail"] == "school_unavailable"


@pytest.mark.anyio
async def test_grades_sync_on_the_live_shell_caches_a_zero_rows_snapshot(harness_factory):
    # Given the school landing on the REAL zero-rows rpt shell (115-1 account)
    harness = harness_factory(_history_shell)
    sid = await harness.seed_session(family="stusco")

    # When the student syncs grades
    response = harness.client.post(GRADES_SYNC_PATH, cookies={"session_id": sid})

    # Then the honest empty result caches session-scoped at 7d TTL
    assert response.status_code == 200
    body = response.json()
    assert body["synced_at"]
    assert body["items"] == []
    assert body["added"] == [] and body["removed"] == [] and body["unchanged"] == []
    assert harness.redis.remaining_ttl(f"grades:{sid}") == 7 * 24 * 3600

    # And GET serves the snapshot without another school call
    got = harness.client.get(GRADES_PATH, cookies={"session_id": sid})
    assert got.status_code == 200
    assert got.json()["synced_at"] == body["synced_at"]
    assert got.json()["items"] == []
    assert len(harness.relay.calls) == 1


@pytest.mark.anyio
async def test_grades_sync_row_identity_diff_across_syncs(harness_factory):
    harness = harness_factory(_rpt_with_rows)
    sid = await harness.seed_session(family="stusco")

    first = harness.client.post(GRADES_SYNC_PATH, cookies={"session_id": sid})
    assert first.status_code == 200
    assert len(first.json()["added"]) == 3  # header row + 2 data rows, verbatim
    assert first.json()["removed"] == [] and first.json()["unchanged"] == []
    assert first.json()["items"][1] == ["M5001", "高等演算法", "3", "95"]

    second = harness.client.post(GRADES_SYNC_PATH, cookies={"session_id": sid})
    assert second.status_code == 200
    assert second.json()["added"] == [] and second.json()["removed"] == []
    assert len(second.json()["unchanged"]) == 3
    assert len(harness.relay.calls) == 2


# ---------- registration checklist + payment receipt ----------


@pytest.mark.anyio
async def test_checklist_happy_path_returns_parsed_rows(harness_factory):
    # Given the live regweb main page (16 checklist anchors, enrollcert button)
    harness = harness_factory(_checklist_page)
    sid = await harness.seed_session()
    response = harness.client.get(CHECKLIST_PATH, cookies={"session_id": sid})
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 16
    assert body["enrollcert_present"] is True
    first = body["items"][0]
    assert set(first) == {"title", "period", "status_text", "out_url"}
    assert "確認個人基本資料" in first["title"]
    assert any("已完成" in item["status_text"] for item in body["items"])
    assert harness.relay.calls == [CHECKLIST_RELAY_URL]


@pytest.mark.anyio
async def test_receipt_happy_path_two_hops_to_pdf(harness_factory):
    # Given the live bills page whose newest bill carries an onclick receipt href
    harness = harness_factory(_payment_then_receipt_pdf)
    sid = await harness.seed_session()
    response = harness.client.get(RECEIPT_PATH, cookies={"session_id": sid})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["cache-control"] == "no-store"
    assert "payment_receipt.pdf" in response.headers["content-disposition"]
    assert response.content == PDF_BYTES
    assert harness.relay.calls == [
        TFSTU_RELAY_URL,
        RECEIPT_RELAY_PREFIX + "tfstudata.asp?act=61&mst_sno=IM1151006292",
    ]


@pytest.mark.anyio
async def test_receipt_without_link_answers_404(harness_factory, monkeypatch):
    # Given a bills page parse that yields zero receipt hrefs
    monkeypatch.setattr(
        "app.api.stu_enroll.parse_payment_bills",
        lambda _html: PaymentPage(dept="", bills=()),
    )
    harness = harness_factory(_payment_page)
    sid = await harness.seed_session()
    response = harness.client.get(RECEIPT_PATH, cookies={"session_id": sid})
    assert response.status_code == 404
    assert response.json()["detail"] == "receipt_not_available"
