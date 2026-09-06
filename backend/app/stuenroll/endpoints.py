"""Raw IO for the stu_enroll family (M1) - thin, typed, jar-threading.

Every helper performs exactly one school request and returns a PageResult
carrying the EVOLVED jar: httpx copies the cookies object handed to
``build_client``, so the caller's jar never receives Set-Cookie (live-proven
invariant; see the package docstring). Transport is an injectable seam exactly
like app/selcrs/endpoints.py.
"""

from dataclasses import dataclass
from typing import Final
from urllib.parse import urlencode

from app.selcrs.endpoints import SELCRS_BASE_URL
from app.selcrs.errors import SelcrsUnavailable
from app.selcrs.http import AsyncBaseTransport, Cookies, build_client, request_school

FORM_CONTENT_TYPE: Final = "application/x-www-form-urlencoded"
FORM_TEXT_ENCODING: Final = "big5"
STU_ENROLL_LOGIN_URL: Final = f"{SELCRS_BASE_URL}/stu_enroll/"
SCO_LOGIN_URL: Final = f"{SELCRS_BASE_URL}/scoreqry/"
SCO_HISTORY_URL: Final = f"{SCO_LOGIN_URL}sco_query.asp?action=811&KIND=3"
REGWEB_BASE_URL: Final = "https://regweb.nsysu.edu.tw/webreg"
TFSTU_RELAY_URL: Final = (
    f"{REGWEB_BASE_URL}/WRegMain3.asp?act=71&out="
    "https://tfstu.nsysu.edu.tw/tfstu/tfstu_login_chk.asp"
)
ENROLLCERT_RELAY_URL: Final = f"{REGWEB_BASE_URL}/WRegMain3.asp?act=71&out=print/enrollcert.asp"


@dataclass(frozen=True, slots=True)
class PageResult:
    """One wire answer plus the evolved cookie jar (return both, always)."""

    content: bytes
    cookies: Cookies
    status_code: int
    content_type: str | None
    location: str | None


async def get_page(
    url: str, jar: Cookies | None, *, transport: AsyncBaseTransport | None = None
) -> PageResult:
    async with build_client(cookies=jar, transport=transport) as client:
        response = await request_school(client, "GET", url)
    return PageResult(
        content=response.content,
        cookies=client.cookies,
        status_code=response.status_code,
        content_type=response.headers.get("content-type"),
        location=response.headers.get("location"),
    )


async def post_form(
    url: str,
    fields: tuple[tuple[str, str], ...],
    jar: Cookies | None,
    *,
    referer: str | None = None,
    transport: AsyncBaseTransport | None = None,
) -> PageResult:
    """POST one classic-ASP form (big5 percent-encoded, like its browsers)."""
    headers = {"Content-Type": FORM_CONTENT_TYPE}
    if referer is not None:
        headers["Referer"] = referer
    async with build_client(cookies=jar, transport=transport) as client:
        response = await request_school(
            client, "POST", url, content=urlencode(list(fields), encoding=FORM_TEXT_ENCODING), headers=headers
        )
    return PageResult(
        content=response.content,
        cookies=client.cookies,
        status_code=response.status_code,
        content_type=response.headers.get("content-type"),
        location=response.headers.get("location"),
    )


async def fetch_validcode(
    url: str, jar: Cookies | None, *, transport: AsyncBaseTransport | None = None
) -> tuple[bytes, Cookies]:
    """One captcha BMP on the evolving jar lineage; answer binds to that lineage."""
    result = await get_page(url, jar, transport=transport)
    if result.status_code != 200 or "image" not in (result.content_type or "").lower():
        raise SelcrsUnavailable(
            f"validcode answered HTTP {result.status_code} ({result.content_type})"
        )
    return result.content, result.cookies
