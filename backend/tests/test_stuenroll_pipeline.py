"""Fan-out pipeline tests (M2) - both legs replay over one MockTransport.

URL-keyed routing (never shared FIFO queues) because the two legs run
concurrently and POST order across families is nondeterministic. The sco
leg's login/handoff pages are SYNTHETIC constructions from the M0
live-verified facts (sco form fields SID/PASSWD/ValidCode + hidden
ACTION/INTYPE, auto-form -> sco_query.asp 302) - no live sco login fixture
exists yet; it is part of the pending capture round.
"""

import time
from pathlib import Path

import httpx
import pytest

from app.stuenroll.pipeline import LegError, fanout_subsystem_logins

FIXTURES = Path(__file__).parent / "fixtures"
STU_LOGIN_PAGE = (FIXTURES / "stuenroll_login_live_1151.html").read_bytes()
CAPTCHA_FAIL_PAGE = (FIXTURES / "stuenroll_loginresp_attempt2_live_1151.html").read_bytes()
STU_HANDOFF_PAGE = (FIXTURES / "stuenroll_hop2_live_1151.html").read_bytes()
REGWEB_MAIN_PAGE = (FIXTURES / "stuenroll_regweb_main_live_1151.html").read_bytes()
GRADES_FRAMESET = (FIXTURES / "stuenroll_grades_live_1151.html").read_bytes()
BMP = (FIXTURES / "stuenroll_validcode_live_1151.bmp").read_bytes()

STUDENT = "M153000099"
PASSWORD = "pw-synth-099"

SCO_LOGIN_PAGE = b"""<html><body><form method="post" action="sco_loginchk.asp">
<input type="hidden" name="ACTION" value="1"><input type="hidden" name="INTYPE" value="1">
<input type="text" name="SID"><input type="password" name="PASSWD">
<input type="text" name="ValidCode"><img src="validcode.asp">
</form></body></html>"""

SCO_HANDOFF_PAGE = b"""<html><body><form method="post" action="sco_query.asp?action=1">
<input type="hidden" name="SID" value="***"><input type="hidden" name="PASSWD" value="***">
<input type="hidden" name="ValidCode" value="0000"><input type="hidden" name="ACTION" value="1">
<input type="hidden" name="INTYPE" value="1"></form>
<script>document.forms[0].submit();</script></body></html>"""

DRIFT_PAGE = b"<html><body>no form here</body></html>"


def _resp(content: bytes, *, status: int = 200, location: str | None = None) -> httpx.Response:
    headers = {"Content-Type": "text/html; charset=utf-8"}
    if location is not None:
        headers["Location"] = location
    return httpx.Response(status, content=content, headers=headers)


def _make_transport(
    *,
    stu_posts: list[httpx.Response] | None = None,
    sco_posts: list[httpx.Response] | None = None,
    sco_login_page: bytes = SCO_LOGIN_PAGE,
    slow_s: float = 0.0,
) -> tuple[httpx.MockTransport, dict[str, list[bytes]]]:
    stu_queue: list[httpx.Response] = list(stu_posts if stu_posts is not None else [])
    sco_queue: list[httpx.Response] = list(sco_posts if sco_posts is not None else [])
    bodies: dict[str, list[bytes]] = {"stu": [], "sco": []}

    def handler(request: httpx.Request) -> httpx.Response:
        if slow_s:
            time.sleep(slow_s)
        url = str(request.url)
        if "validcode.asp" in url:
            return httpx.Response(200, content=BMP, headers={"Content-Type": "Image/BMP"})
        if request.method == "POST":
            if "stu_enroll_loginchk" in url:
                bodies["stu"].append(request.content)
                return stu_queue.pop(0)
            if "sco_loginchk" in url:
                bodies["sco"].append(request.content)
                return sco_queue.pop(0)
            if "wregloginchk" in url:
                return _resp(b"", status=302, location="wregmain3.asp?act=11")
            if "sco_query" in url:
                return _resp(b"", status=302, location="sco_query.asp?action=101")
            raise AssertionError(f"unscripted POST: {url}")
        if "wregmain3" in url:
            return _resp(REGWEB_MAIN_PAGE)
        if "sco_query" in url:
            return _resp(GRADES_FRAMESET)
        if "/stu_enroll/" in url:
            return _resp(STU_LOGIN_PAGE)
        if "/scoreqry/" in url:
            return _resp(sco_login_page)
        raise AssertionError(f"unscripted GET: {url}")

    return httpx.MockTransport(handler), bodies


@pytest.mark.anyio
async def test_fanout_both_legs_available_under_deadline() -> None:
    transport, bodies = _make_transport(
        stu_posts=[_resp(CAPTCHA_FAIL_PAGE), _resp(STU_HANDOFF_PAGE)],
        sco_posts=[_resp(SCO_HANDOFF_PAGE)],
    )
    result = await fanout_subsystem_logins(
        STUDENT,
        PASSWORD,
        solve=lambda _bmp: "1234",
        transport=transport,
    )
    assert result.regweb_available is True
    assert result.sco_available is True
    assert result.regweb.jar is not None and result.sco.jar is not None
    assert result.regweb.error is None and result.sco.error is None
    assert result.regweb.attempts == 2  # one captcha reject, then the handoff
    assert result.sco.attempts == 1
    stu_first = bodies["stu"][0].decode("big5", errors="replace")
    assert f"IDtmp={STUDENT}" in stu_first and "ValidCode=1234" in stu_first
    sco_body = bodies["sco"][0].decode("big5", errors="replace")
    assert f"SID={STUDENT}" in sco_body
    assert f"PASSWD={PASSWORD}" in sco_body
    assert "ACTION=1" in sco_body  # verbatim hidden fields ride along


@pytest.mark.anyio
async def test_fanout_sco_captcha_exhaustion_keeps_regweb_available() -> None:
    transport, _bodies = _make_transport(
        stu_posts=[_resp(STU_HANDOFF_PAGE)],
        sco_posts=[_resp(CAPTCHA_FAIL_PAGE) for _ in range(5)],
    )
    result = await fanout_subsystem_logins(
        STUDENT,
        PASSWORD,
        solve=lambda _bmp: "1234",
        transport=transport,
    )
    assert result.regweb_available is True
    assert result.sco_available is False
    assert result.sco.error is LegError.CAPTCHA_BUDGET
    assert result.sco.jar is None
    assert result.sco.attempts == 5


@pytest.mark.anyio
async def test_fanout_deadline_marks_unfinished_legs_timeout() -> None:
    transport, _bodies = _make_transport(
        stu_posts=[_resp(STU_HANDOFF_PAGE)],
        sco_posts=[_resp(SCO_HANDOFF_PAGE)],
        slow_s=0.3,
    )
    started = time.monotonic()
    result = await fanout_subsystem_logins(
        STUDENT,
        PASSWORD,
        timeout_s=0.05,
        solve=lambda _bmp: "1234",
        transport=transport,
    )
    wall = time.monotonic() - started
    assert result.regweb_available is False and result.sco_available is False
    assert result.regweb.error is LegError.TIMEOUT
    assert result.sco.error is LegError.TIMEOUT
    assert wall < 2.0  # bounded: never hangs past the handler's own sleep
