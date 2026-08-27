"""SSO2 tri-state classification against a scripted school transport.

Covers plan todo 3 Acceptance:
- SUCCESS requires ALL of 302 + Location containing main_frame + Set-Cookie;
  each missing element flips the outcome to UNKNOWN (SelcrsUnavailable).
- CREDENTIAL-FAIL needs the Big5 failure marker, tolerant to full/half-width
  punctuation, interior whitespace, and alert/meta-refresh wrappers.
- follow_redirects=False is pinned (the 302 must NOT be followed - a follow
  would destroy the classification and double-hit the school).
"""

import httpx
import pytest

from app.selcrs.endpoints import login_sso2
from app.selcrs.errors import SelcrsUnavailable
from app.selcrs.http import build_client
from app.selcrs.sso2 import Sso2Outcome
from tests.conftest import StubTransport


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _big5(text: str) -> bytes:
    """Encode a school HTML snippet exactly as the school would emit it."""
    return text.encode("big5hkscs")


async def _success_handler(request: httpx.Request) -> httpx.Response:
    assert request.method == "POST"
    assert request.url.path == "/menu4/Studcheck_sso2.asp"
    return httpx.Response(
        302,
        headers={
            "Location": "/menu4/main_frame.asp",
            "Set-Cookie": "ASPSESSIONIDQABRCD=KLMNFGHIJK; path=/",
        },
        content=b"",
    )


@pytest.mark.anyio
async def test_sso2_success_needs_302_location_mainframe_and_set_cookie() -> None:
    # Given the school's canonical success shape
    transport = StubTransport(_success_handler)

    # When one SSO2 attempt runs
    result = await login_sso2("B123456789", "123456", transport=transport)

    # Then it is SUCCESS with a fresh session jar, exactly one request fired
    assert result.outcome is Sso2Outcome.SUCCESS
    assert result.cookies.get("ASPSESSIONIDQABRCD") == "KLMNFGHIJK"
    assert result.detail is None
    # And the 302 was NOT followed (follow_redirects=False pinned globally):
    # a follow would have produced a second GET to /menu4/main_frame.asp
    assert len(transport.requests) == 1
    assert build_client().follow_redirects is False


@pytest.mark.anyio
async def test_sso2_uses_base64md5_password_field_over_the_wire() -> None:
    captured_bodies: list[bytes] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured_bodies.append(request.content)
        return await _success_handler(request)

    transport = StubTransport(handler)
    result = await login_sso2("B123456789", "123456", transport=transport)

    # Then the wire form carries stuid verbatim and SPassword=base64md5(...)
    body = captured_bodies[0].decode("ascii")
    assert "stuid=B123456789" in body
    assert "SPassword=4QrcOUm6Wau%2BVuBX8g%2BIPg%3D%3D" in body
    assert result.outcome is Sso2Outcome.SUCCESS


_FAIL_BODIES = (
    "學號碼密碼不符",  # bare marker (canonical phrase)
    "密碼輸入錯誤：學號碼密碼不符，請重新輸入！!",  # half/full-width punctuation mixed
    "<script>alert('學號碼密碼不符');location.href='../login.asp';</script>",  # alert wrapper
    "<html><head><meta http-equiv='refresh' content='3;url=../login.asp'></head>"
    "<body>學號碼　密碼　不符</body></html>",  # meta-refresh wrapper + interior whitespace
)


@pytest.mark.anyio
@pytest.mark.parametrize("fail_html", _FAIL_BODIES)
async def test_sso2_credential_fail_detected_across_marker_variants(fail_html: str) -> None:
    # Given a 200 body carrying the failure marker in some tolerated wrapper
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_big5(fail_html))

    transport = StubTransport(handler)

    # When one SSO2 attempt runs
    result = await login_sso2("B123456789", "000000", transport=transport)

    # Then it classifies CREDENTIAL_FAIL and yields NO session jar upstream
    assert result.outcome is Sso2Outcome.CREDENTIAL_FAIL
    assert result.detail == "學號碼密碼不符"
    assert len(result.cookies.jar) == 0


@pytest.mark.anyio
@pytest.mark.parametrize(
    "response",
    (
        # 200 but no marker (e.g. an unexpected portal page)
        httpx.Response(200, content=_big5("<html><body>課程系統</body></html>")),
        # 302 without any Set-Cookie
        httpx.Response(302, headers={"Location": "/menu4/main_frame.asp"}, content=b""),
        # 302 + Set-Cookie but Location points elsewhere (no main_frame)
        httpx.Response(
            302,
            headers={
                "Location": "/menu4/query/query_menu.asp",
                "Set-Cookie": "ASPSESSION=AAA; path=/",
            },
            content=b"",
        ),
        # straight 500
        httpx.Response(500, content=_big5("系統忙碌中")),
    ),
)
async def test_sso2_unknown_shapes_raise_selcrs_unavailable(response: httpx.Response) -> None:
    # Given a response that matches neither SUCCESS nor CREDENTIAL-FAIL
    async def handler(request: httpx.Request) -> httpx.Response:
        return response

    transport = StubTransport(handler)

    # When/Then the attempt raises the breaker-path error (never lockout-fed)
    with pytest.raises(SelcrsUnavailable):
        await login_sso2("B123456789", "123456", transport=transport)
