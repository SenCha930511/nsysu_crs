"""Login-response classification tests (M1; live fixtures only)."""

from pathlib import Path

from app.stuenroll.classify import (
    LoginVerdict,
    classify_login_response,
    is_captcha_fail,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_confirmed_wrong_code_answer_classifies_captcha_fail() -> None:
    html = _load("stuenroll_loginresp_attempt2_live_1151.html")
    assert is_captcha_fail(html) is True
    assert classify_login_response(html) is LoginVerdict.CAPTCHA_FAIL


def test_handoff_pages_classify_as_handoff() -> None:
    # attempt1 = the loginchk SUCCESS relay (347B Studpassform->wregloginchk);
    # hop1 = the sco post-login relay; hop2 = the wregloginchk->2 relay
    for name in (
        "stuenroll_loginresp_attempt1_live_1151.html",
        "stuenroll_hop1_live_1151.html",
        "stuenroll_hop2_live_1151.html",
    ):
        assert classify_login_response(_load(name)) is LoginVerdict.HANDOFF


def test_interactive_login_page_classifies_unknown_never_fail() -> None:
    assert classify_login_response(_load("stuenroll_login_live_1151.html")) is LoginVerdict.UNKNOWN


def test_gibberish_is_unknown() -> None:
    assert classify_login_response("<html><body>404 not found</body></html>") is LoginVerdict.UNKNOWN
