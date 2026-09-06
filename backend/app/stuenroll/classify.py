"""Login-response classification for stu_enroll-family interactive logins.

Confirmed live (M0, 2026-09-04; fixture stuenroll_loginresp_attempt2_live_1151):
a WRONG captcha answer is HTTP 200 with 「驗證碼錯誤。/ Incorrect verified
code!!」 and a 回首頁 link to index.asp.

Everything that is NOT a wrong-code answer and NOT a handoff page is UNKNOWN
here - the school's credential-failure shape was never observed (the account
owner always supplied the right password, and the probe never spends a wrong
one), so no marker is fabricated for it. UNKNOWN is the designed-safe path: it
feeds the breaker instead of guessing.
"""

import unicodedata
from enum import Enum
from typing import Final

from app.stuenroll.handoff import read_handoff

WRONG_CODE_MARKERS: Final = ("驗證碼錯誤", "Incorrect verified code")


class LoginVerdict(Enum):
    """Tri-state for one decoded login POST answer."""

    HANDOFF = "handoff"
    CAPTCHA_FAIL = "captcha_fail"
    UNKNOWN = "unknown"


def _normalize(text: str) -> str:
    """NFKC fold + drop whitespace (same tolerance as sso2/solver markers)."""
    return "".join(unicodedata.normalize("NFKC", text).split())


_NORMALIZED_WRONG_CODE: Final = tuple(_normalize(marker) for marker in WRONG_CODE_MARKERS)


def is_captcha_fail(html_text: str) -> bool:
    normalized = _normalize(html_text)
    return any(marker in normalized for marker in _NORMALIZED_WRONG_CODE)


def classify_login_response(html_text: str) -> LoginVerdict:
    """Classify one decoded interactive-login response.

    Order matters: the wrong-code marker wins over structure, because a small
    error page could otherwise parse as a form page.

    """
    if is_captcha_fail(html_text):
        return LoginVerdict.CAPTCHA_FAIL
    if read_handoff(html_text) is not None:
        return LoginVerdict.HANDOFF
    return LoginVerdict.UNKNOWN
