"""Interactive-login flow tests (M1) - hermetic MockTransport replays of the
live M0 wire: captcha-fail then handoff then relay chain to the main page."""

from pathlib import Path

import httpx
import pytest

from app.stuenroll.login import STU_ENROLL_ROLES, interactive_login

FIXTURES = Path(__file__).parent / "fixtures"
LOGIN_URL = "https://selcrs.nsysu.edu.tw/stu_enroll/"
LOGIN_PAGE = (FIXTURES / "stuenroll_login_live_1151.html").read_bytes()
CAPTCHA_FAIL_PAGE = (FIXTURES / "stuenroll_loginresp_attempt2_live_1151.html").read_bytes()
# The hop2 relay (wregloginchk -> wregloginchk2) stands in for the login-success
# handoff: same structural shape the walker must follow into the redirect.
HANDOFF_PAGE = (FIXTURES / "stuenroll_hop2_live_1151.html").read_bytes()
MAIN_PAGE = (FIXTURES / "stuenroll_regweb_main_live_1151.html").read_bytes()
BMP = (FIXTURES / "stuenroll_validcode_live_1151.bmp").read_bytes()

STUDENT = "M153000099"
PASSWORD = "pw-synth-099"


def _make_transport(scripted_posts: list[httpx.Response], hits: list[str], bodies: list[bytes]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        hits.append(url)
        if "validcode.asp" in url:
            return httpx.Response(200, content=BMP, headers={"Content-Type": "Image/BMP"})
        if request.method == "POST":
            bodies.append(request.content)
            assert scripted_posts, f"unexpected extra POST: {url}"
            return scripted_posts.pop(0)
        if "wregmain3" in url:
            return httpx.Response(
                200, content=MAIN_PAGE, headers={"Content-Type": "text/html; charset=utf-8"}
            )
        if "/stu_enroll/" in url:
            return httpx.Response(
                200, content=LOGIN_PAGE, headers={"Content-Type": "text/html; charset=utf-8"}
            )
        return httpx.Response(
            200, content=MAIN_PAGE, headers={"Content-Type": "text/html; charset=utf-8"}
        )

    return httpx.MockTransport(handler)


def _resp(content: bytes, *, status: int = 200, location: str | None = None) -> httpx.Response:
    headers = {"Content-Type": "text/html; charset=utf-8"}
    if location is not None:
        headers["Location"] = location
    return httpx.Response(status, content=content, headers=headers)


@pytest.mark.anyio
async def test_login_retries_on_wrong_code_then_walks_the_relay_chain() -> None:
    hits: list[str] = []
    bodies: list[bytes] = []
    transport = _make_transport(
        [
            _resp(CAPTCHA_FAIL_PAGE),
            _resp(HANDOFF_PAGE),
            _resp(b"", status=302, location="wregmain3.asp?act=11"),
        ],
        hits,
        bodies,
    )
    outcome = await interactive_login(
        STUDENT,
        PASSWORD,
        roles=STU_ENROLL_ROLES,
        login_url=LOGIN_URL,
        solve=lambda _bmp: "1234",
        transport=transport,
    )
    assert outcome.ok is True
    assert outcome.attempts == 2
    assert outcome.captcha_rejects == 1
    assert outcome.landing is not None
    assert outcome.landing.url.endswith("wregmain3.asp?act=11")
    assert outcome.landing.hops == 1
    assert outcome.landing.redirects == 1
    assert outcome.landing.content == MAIN_PAGE

    assert len(bodies) == 3  # 2x loginchk + 1x relay forward
    first_body = bodies[0].decode("big5", errors="replace")
    assert f"IDtmp={STUDENT}" in first_body
    assert f"passwdtmp={PASSWORD}" in first_body
    assert "ValidCode=1234" in first_body
    relay_body = bodies[2].decode("big5", errors="replace")
    assert "ID=" in relay_body and "passwd=" in relay_body
    assert f"{STUDENT}" not in relay_body  # relay forwards the SCHOOL's fields


@pytest.mark.anyio
async def test_login_exhausts_captcha_budget_into_not_ok() -> None:
    hits: list[str] = []
    bodies: list[bytes] = []
    transport = _make_transport([_resp(CAPTCHA_FAIL_PAGE) for _ in range(5)], hits, bodies)
    outcome = await interactive_login(
        STUDENT,
        PASSWORD,
        roles=STU_ENROLL_ROLES,
        login_url=LOGIN_URL,
        solve=lambda _bmp: "1234",
        transport=transport,
    )
    assert outcome.ok is False
    assert outcome.landing is None
    assert outcome.attempts == 5
    assert outcome.captcha_rejects == 5
    assert len(bodies) == 5  # all five attempts were captcha rejects
