"""Handoff detection + chain walker tests (M1; M0 fixtures drive every shape).

Positive handoff pages: hop1/hop2/attempt1 (tiny, auto-submit, all-hidden).
Negatives: the 32KB interactive login page, the captcha-fail error page, the
regweb checklist (aux_submit is NOT an auto-submit form).
"""

from pathlib import Path

import httpx
import pytest

from app.stuenroll.endpoints import PageResult
from app.stuenroll.handoff import read_handoff, walk_chain

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _handoff_pages() -> list[str]:
    return [_load("stuenroll_hop1_live_1151.html"), _load("stuenroll_hop2_live_1151.html")]


def test_handoff_detected_with_action_and_hidden_only_inputs() -> None:
    for html in _handoff_pages():
        form = read_handoff(html)
        assert form is not None
        assert form.action
        assert form.fields
        assert all(name for name, _value in form.fields)


def test_wregloginchk_relay_targets_wregloginchk2_with_creds() -> None:
    form = read_handoff(_load("stuenroll_hop2_live_1151.html"))
    assert form is not None
    assert form.action == "wregloginchk2.asp"
    assert {name for name, _value in form.fields} >= {"ID", "passwd"}


def test_enrollcert_relay_targets_the_cert_printer() -> None:
    form = read_handoff(_load("stuenroll_hop1_live_1151.html"))
    assert form is not None
    assert form.action.endswith("print/enrollcert.asp")


def test_interactive_login_page_is_not_a_handoff() -> None:
    assert read_handoff(_load("stuenroll_login_live_1151.html")) is None


def test_captcha_fail_page_is_not_a_handoff() -> None:
    assert read_handoff(_load("stuenroll_loginresp_attempt2_live_1151.html")) is None


def test_regweb_main_is_not_a_handoff() -> None:
    assert read_handoff(_load("stuenroll_regweb_main_live_1151.html")) is None


def _page(content: bytes, *, status: int = 200, location: str | None = None) -> PageResult:
    return PageResult(
        content=content,
        cookies=httpx.Cookies(),
        status_code=status,
        content_type="text/html; charset=utf-8",
        location=location,
    )


@pytest.mark.anyio
async def test_walk_chain_follows_handoff_then_redirect_and_forwards_fields() -> None:
    hop1 = (FIXTURES / "stuenroll_hop1_live_1151.html").read_bytes()
    sent: list[tuple[str, tuple[tuple[str, str], ...], str]] = []

    async def fake_get(url: str, jar: httpx.Cookies | None) -> PageResult:
        assert url.endswith("wregmain3.asp?act=11")
        return _page(b"<html>MAIN</html>")

    async def fake_post(
        url: str, fields: tuple[tuple[str, str], ...], jar: httpx.Cookies | None, referer: str
    ) -> PageResult:
        sent.append((url, fields, referer))
        return _page(b"", status=302, location="wregmain3.asp?act=11")

    result = await walk_chain(
        get=fake_get,
        post=fake_post,
        decode=lambda raw: raw.decode("utf-8", errors="replace"),
        start_status=200,
        start_content=hop1,
        start_url="https://regweb.nsysu.edu.tw/webreg/wregloginchk.asp",
    )
    assert result.hops == 1
    assert result.redirects == 1
    assert result.url.endswith("wregmain3.asp?act=11")
    assert result.content == b"<html>MAIN</html>"
    assert len(sent) == 1
    url, fields, referer = sent[0]
    assert url.startswith("https://")
    assert referer == "https://regweb.nsysu.edu.tw/webreg/wregloginchk.asp"
    live_form = read_handoff(hop1.decode("utf-8"))
    assert live_form is not None
    assert fields == live_form.fields


@pytest.mark.anyio
async def test_walk_chain_respects_the_hop_budget() -> None:
    hop1 = (FIXTURES / "stuenroll_hop1_live_1151.html").read_bytes()

    async def fake_get(url: str, jar: httpx.Cookies | None) -> PageResult:
        raise AssertionError("budget-exhausted chain must never GET")

    async def fake_post(
        url: str, fields: tuple[tuple[str, str], ...], jar: httpx.Cookies | None, referer: str
    ) -> PageResult:
        return _page(hop1)

    result = await walk_chain(
        get=fake_get,
        post=fake_post,
        decode=lambda raw: raw.decode("utf-8", errors="replace"),
        start_status=200,
        start_content=hop1,
        start_url="https://example.test/entry",
        max_hops=3,
    )
    assert result.hops == 3
    assert result.content == hop1
