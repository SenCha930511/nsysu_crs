"""Fixture-driven SSO2 tri-state classification across BOTH wire encodings.

Pins the 2026-08-27 live-verified bug: under the old all-big5hkscs decode,
the real UTF-8 failure page (fixture sso2_fail_live_1151.html, captured
tonight) mojibake'd and mis-classified as UNKNOWN (breaker) instead of
CREDENTIAL-FAIL. With per-response sniffing the same bytes classify correctly,
and Big5-era simulated pages keep classifying exactly as before.
"""

from pathlib import Path

import httpx
import pytest

from app.selcrs.decode import decode_body, resolve_charset
from app.selcrs.endpoints import login_sso2
from app.selcrs.errors import SelcrsUnavailable
from app.selcrs.sso2 import FAILURE_MARKER, Sso2Outcome, classify_sso2_response
from tests.conftest import StubTransport

FIXTURES = Path(__file__).resolve().parent / "fixtures"

LIVE_FAIL_UTF8 = (FIXTURES / "sso2_fail_live_1151.html").read_bytes()
SYNTHETIC_FAIL_BIG5 = (FIXTURES / "sso2_fail_big5_synthetic.html").read_bytes()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_live_utf8_sso2_fail_fixture_classifies_credential_fail() -> None:
    # Given the real 115-1 failure page exactly as captured (UTF-8 bytes,
    # no charset on the wire back to us -> meta sniffing must decide)
    assert resolve_charset(LIVE_FAIL_UTF8) == "utf-8"

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=LIVE_FAIL_UTF8)

    # When one SSO2 attempt runs against those bytes
    result = await login_sso2("B123456789", "000000", transport=StubTransport(handler))

    # Then it is CREDENTIAL-FAIL (never the UNKNOWN breaker path), no jar
    assert result.outcome is Sso2Outcome.CREDENTIAL_FAIL
    assert result.detail == FAILURE_MARKER
    assert len(result.cookies.jar) == 0
    # And decoding is clean Unicode (pre-fix this was big5hkscs mojibake)
    body = decode_body(LIVE_FAIL_UTF8)
    assert FAILURE_MARKER in "".join(body.split())
    assert "資料錯誤" in body
    assert "\ufffd" not in body


def test_live_utf8_fail_fixture_under_old_policy_would_mojibake() -> None:
    # Given the live UTF-8 fixture force-decoded the OLD way (all-big5hkscs)
    legacy = LIVE_FAIL_UTF8.decode("big5hkscs", errors="replace")

    # When the classifier's own normalization runs over that mojibake
    # Then the marker is absent -> proves the old policy flipped this live
    # page to UNKNOWN (the regression this suite pins)
    assert FAILURE_MARKER not in "".join(legacy.split())


@pytest.mark.anyio
async def test_synthetic_big5_sso2_fail_fixture_classifies_credential_fail() -> None:
    # Given a Big5-era simulated failure page (alert wrapper, big5 meta)
    assert resolve_charset(SYNTHETIC_FAIL_BIG5) == "big5hkscs"

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=SYNTHETIC_FAIL_BIG5)

    # When one SSO2 attempt runs
    result = await login_sso2("B123456789", "000000", transport=StubTransport(handler))

    # Then the marker still matches on decoded Unicode, exactly as pre-fix
    assert result.outcome is Sso2Outcome.CREDENTIAL_FAIL
    assert result.detail == FAILURE_MARKER


@pytest.mark.anyio
async def test_utf8_302_shape_classifies_success_and_is_not_followed() -> None:
    # Given a canonical success redirect whose body is UTF-8 page bytes
    utf8_page = "<html><body>正在切換至主畫面…</body></html>".encode("utf-8")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={
                "Location": "/menu4/main_frame.asp",
                "Set-Cookie": "ASPSESSIONIDUTF8=XYZ; path=/",
            },
            content=utf8_page,
        )

    transport = StubTransport(handler)
    result = await login_sso2("B123456789", "123456", transport=transport)

    # Then SUCCESS with the issued jar, and the 302 was NOT followed
    assert result.outcome is Sso2Outcome.SUCCESS
    assert result.cookies.get("ASPSESSIONIDUTF8") == "XYZ"
    assert len(transport.requests) == 1


def test_big5_unknown_page_raises_selcrs_unavailable() -> None:
    # Given a Big5-era 200 page without any failure marker (heuristic lane:
    # undeclared, strict-UTF-8-invalid bytes -> big5hkscs)
    raw = "<html><body>系統維護中，請稍後再試。</body></html>".encode("big5hkscs")
    with pytest.raises(UnicodeDecodeError):
        raw.decode("utf-8", errors="strict")  # prove the heuristic's premise
    response = httpx.Response(200, content=raw)

    # When/Then classification raises the breaker-path error, never lockout
    with pytest.raises(SelcrsUnavailable):
        classify_sso2_response(response)


def test_live_page_fixtures_detect_utf8_and_decode_clean() -> None:
    # Given tonight's live page captures (UTF-8 per their <meta> and bytes)
    slt = (FIXTURES / "slt_result_live_1151.html").read_bytes()
    studfun = (FIXTURES / "studfun_closed_live_1151.html").read_bytes()

    # When resolved + decoded through the new policy
    # Then both sniff utf-8 and decode to clean Unicode with real markers
    for raw, expected in ((slt, "課程名稱"), (studfun, "選課關閉")):
        assert resolve_charset(raw) == "utf-8"
        text = decode_body(raw)
        assert expected in text
        assert "\ufffd" not in text
