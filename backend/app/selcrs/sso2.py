"""SSO2 login tri-state classification.

Contract (plan todo 3):

- ``SUCCESS``:          HTTP 302 AND ``Location`` contains ``main_frame`` AND
                        at least one ``Set-Cookie`` header.
- ``CREDENTIAL_FAIL``:  HTTP 200 AND the body carries the school's failure
                        marker (see ``_FAILURE_MARKER``).
- ``UNKNOWN``:          anything else. Raised as ``SelcrsUnavailable``; feeds
                        the breaker, NEVER the per-account lockout.

Marker tolerance: the school emits the failure line in Big5 with varying
full/half-width punctuation and unpredictable wrappers
(``<script>alert('...')</script>`` or ``<meta http-equiv=refresh ...>``).
We therefore compare on a NORMALIZED body: NFKC flattens full-width
punctuation/digits to half-width, then all whitespace is dropped, then a
plain substring search. Wrapper HTML cannot hide the marker because it only
adds text around it, not inside it.
"""

import unicodedata
from enum import StrEnum
from typing import Final

import httpx

from app.selcrs.decode import decode_body
from app.selcrs.errors import SelcrsUnavailable

# The school's human-readable SSO2 failure phrase (Big5). Archaeological
# source: .omo/drafts research ("錯密碼回 200 含「學號碼密碼不符」");
# live-captured confirmation tracked for todo 4 (sso2_fail_*.html).
FAILURE_MARKER: Final = "學號碼密碼不符"


class Sso2Outcome(StrEnum):
    """Tri-state result of one SSO2 attempt (UNKNOWN raises, see module doc)."""

    SUCCESS = "success"
    CREDENTIAL_FAIL = "credential_fail"


def _normalize_body(text: str) -> str:
    """Flatten full/half-width variants (NFKC) and drop all whitespace."""
    return "".join(unicodedata.normalize("NFKC", text).split())


def classify_sso2_response(response: httpx.Response) -> Sso2Outcome:
    """Classify one raw SSO2 POST response. UNKNOWN raises SelcrsUnavailable."""
    body = decode_body(response.content)
    if (
        response.status_code == 302
        and "main_frame" in response.headers.get("location", "")
        and response.headers.get_list("set-cookie")
    ):
        return Sso2Outcome.SUCCESS
    if response.status_code == 200 and FAILURE_MARKER in _normalize_body(body):
        return Sso2Outcome.CREDENTIAL_FAIL
    raise SelcrsUnavailable("unrecognised SSO2 response shape")
