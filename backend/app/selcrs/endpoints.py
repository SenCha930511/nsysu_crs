"""Endpoint skeletons for the selcrs adapter (plan todo 3).

Raw IO only. What this layer does NOT do (owned by later todos): catalog
HTML parsing (todo 6), Studfun stage detection (todo 13), write payload
construction (todo 14/15). Each function below performs exactly one school
request (plus transport backoff) and returns the raw decoded payload or a
tri-state classification.

HTTP-level invariant: classic ASP returns 200 for successful page/form
responses, so page endpoints require status 200; any other status is an
UNKNOWN school behaviour -> SelcrsUnavailable (breaker path). SSO2 is the
one endpoint where non-200 statuses are meaningful and is classified by
sso2.py instead. Capture-phase (todo 4) recordings will confirm per-endpoint
status behaviour against live fixtures.
"""

import time
from dataclasses import dataclass
from typing import Final

import httpx

from app.selcrs.decode import decode_body
from app.selcrs.errors import SelcrsUnavailable
from app.selcrs.http import build_client, request_school
from app.selcrs.sso2 import FAILURE_MARKER, Sso2Outcome, classify_sso2_response
from app.selcrs.transform import base64md5

SELCRS_BASE_URL: Final = "https://selcrs.nsysu.edu.tw"


def _require_200(response: httpx.Response, endpoint_name: str) -> str:
    if response.status_code != 200:
        raise SelcrsUnavailable(f"{endpoint_name} responded HTTP {response.status_code}")
    return decode_body(response.content, response.headers.get("content-type"))


@dataclass(frozen=True, slots=True)
class ValidcodeResult:
    """One captcha image plus the cookie jar it was issued under."""

    image_bytes: bytes
    cookies: httpx.Cookies


@dataclass(frozen=True, slots=True)
class Sso2Result:
    """Outcome of one SSO2 login attempt.

    ``cookies`` carries the fresh selcrs session jar on SUCCESS only; the jar
    is NEVER persisted to Postgres (Redis-only policy, docs/architecture.md).
    ``detail`` is the normalized failure marker on CREDENTIAL_FAIL.
    """

    outcome: Sso2Outcome
    cookies: httpx.Cookies
    detail: str | None


@dataclass(frozen=True, slots=True)
class CatalogQuery:
    """dplycourse.asp filter fields. Chinese-text fields do NOT exist here.

    ``teacher``/``crsname`` are hard-cleared in the payload builder on
    purpose (plan: fields containing Chinese text stay empty; enumerate by
    codes only) - they cannot be passed through this type at all.
    """

    year_sem: str  # D0 = YYY+S, e.g. "1151"
    deg_cod: str = ""
    d1: str = ""
    d2: str = ""
    class_cod: str = ""
    sect_cod: str = ""
    sdg_cod: str = ""
    spec: str = ""
    t3: str = ""
    cb1: str = ""
    wkday: str = ""
    sect: str = ""
    his: str = ""
    idno: str = ""
    item: str = ""


def _catalog_form(query: CatalogQuery, validcode: str) -> dict[str, str]:
    """Build the dplycourse.asp POST body. Field set per plan todo 6 References."""
    return {
        "HIS": query.his,
        "IDNO": query.idno,
        "ITEM": query.item,
        "D0": query.year_sem,
        "DEG_COD": query.deg_cod,
        "D1": query.d1,
        "D2": query.d2,
        "CLASS_COD": query.class_cod,
        "SECT_COD": query.sect_cod,
        "TYP": "1",
        "SDG_COD": query.sdg_cod,
        # Center out in Chinese are pinned empty: Big5 query-side mojibake on
        # the school host made name searches unreliable; codes only.
        "teacher": "",
        "crsname": "",
        "SPEC": query.spec,
        "T3": query.t3,
        "CB1": query.cb1,
        "WKDAY": query.wkday,
        "SECT": query.sect,
        "nowhis": "1",
        "ValidCode": validcode,
    }


async def fetch_validcode(
    *,
    cookies: httpx.Cookies | None = None,
    epoch: int | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ValidcodeResult:
    """GET a captcha BMP. Captcha lane: semaphore-of-1, per-run jar.

    When no ``cookies`` jar is supplied, a fresh jar is created - two
    concurrent catalog runs therefore never share a jar (their captcha
    answers would otherwise deliver the wrong run's session-cookie state).
    Binary body is returned untouched (never Big5-decoded).
    """
    jar = cookies if cookies is not None else httpx.Cookies()
    async with build_client(cookies=jar, transport=transport) as client:
        # httpx copies the constructor's jar; response cookies land on the
        # client's own jar, so the session jar to hand back is client.cookies.
        response = await request_school(
            client,
            "GET",
            f"{SELCRS_BASE_URL}/menu1/validcode.asp",
            params={"epoch": epoch if epoch is not None else int(time.time() * 1000)},
            captcha_parented=True,
        )
        session = client.cookies
    if response.status_code != 200 or not response.content:
        raise SelcrsUnavailable(
            f"validcode responded HTTP {response.status_code} with empty body"
            if not response.content
            else f"validcode responded HTTP {response.status_code}"
        )
    return ValidcodeResult(image_bytes=response.content, cookies=session)


async def login_sso2(
    student_no: str,
    password: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Sso2Result:
    """POST Studcheck_sso2.asp; tri-state per sso2.py.

    ``password`` exists in memory only for the duration of this call and is
    transformed (base64md5) into the form field; it is never stored, never
    logged, never part of any error detail (password zero-persistence
    policy, docs/architecture.md).
    """
    jar = httpx.Cookies()
    async with build_client(cookies=jar, transport=transport) as client:
        response = await request_school(
            client,
            "POST",
            f"{SELCRS_BASE_URL}/menu4/Studcheck_sso2.asp",
            data={"stuid": student_no, "SPassword": base64md5(password)},
        )
        # The Set-Cookie session was merged into the client's own jar (httpx
        # copies constructor jars); snapshot it before the client closes.
        session = client.cookies
    outcome = classify_sso2_response(response)
    if outcome is Sso2Outcome.SUCCESS:
        return Sso2Result(outcome=outcome, cookies=session, detail=None)
    return Sso2Result(outcome=outcome, cookies=httpx.Cookies(), detail=FAILURE_MARKER)


async def get_studfun(
    cookies: httpx.Cookies,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    """GET menu4/Studfun.asp (stage/links page) as decoded HTML."""
    async with build_client(cookies=cookies, transport=transport) as client:
        response = await request_school(client, "GET", f"{SELCRS_BASE_URL}/menu4/Studfun.asp")
    return _require_200(response, "Studfun.asp")


async def fetch_front_page(
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    """GET the site front page (選課日程 table lives here) as decoded HTML.

    Public and cookie-less: no session jar is attached by construction.
    """
    async with build_client(transport=transport) as client:
        response = await request_school(client, "GET", f"{SELCRS_BASE_URL}/")
    return _require_200(response, "front page")


async def get_slt_result(
    cookies: httpx.Cookies,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    """GET menu4/query/slt_result.asp (real selections) as decoded HTML."""
    async with build_client(cookies=cookies, transport=transport) as client:
        response = await request_school(
            client, "GET", f"{SELCRS_BASE_URL}/menu4/query/slt_result.asp"
        )
    return _require_200(response, "slt_result.asp")


async def fetch_qrycourse(
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    """GET menu1/qrycourse.asp?HIS=2 (catalog discovery page) as decoded HTML.

    Public endpoint, no captcha: rides the plain global lane (the catalog
    pipeline's only non-captcha school call; todo 6 parses the ``YRSM``
    <select> from it).
    """
    async with build_client(transport=transport) as client:
        response = await request_school(
            client,
            "GET",
            f"{SELCRS_BASE_URL}/menu1/qrycourse.asp",
            params={"HIS": "2"},
        )
    return _require_200(response, "qrycourse.asp")


async def fetch_catalog_page(
    query: CatalogQuery,
    *,
    validcode: str,
    cookies: httpx.Cookies,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    """POST menu1/dplycourse.asp for catalog page 1; decoded HTML out.

    The caller (catalog pipeline, todo 6) owns pagination + parsing and must
    pass the SAME per-run jar that solved ``validcode`` (captcha answer binds
    to that jar's session). This POST spends the captcha answer, so it rides
    the captcha-parented lane: fully serialized process-wide and still inside
    the global school cap of 2 (plan: 驗證碼相關請求 per-run jar +
    semaphore=1 全程序列化).

    Two live-verified paging-contract facts (2026-08-28, qa/06-live.log):

    - The POST URL must carry the ``?page=1`` query: the school only embeds
      the session-bound ``?a=<token>`` paging anchors when the request URL
      has a query string; a bare POST renders broken ``dplycourse.asp&...``
      links and pagination is impossible.
    - Pages 2..N do NOT re-POST: they are GETs on those embedded anchors -
      see fetch_catalog_page_get.
    """
    async with build_client(cookies=cookies, transport=transport) as client:
        response = await request_school(
            client,
            "POST",
            f"{SELCRS_BASE_URL}/menu1/dplycourse.asp",
            params={"page": 1},
            data=_catalog_form(query, validcode),
            captcha_parented=True,
        )
    return _require_200(response, "dplycourse.asp")


async def fetch_catalog_page_get(
    cookies: httpx.Cookies,
    page_path: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    """GET one catalog result page via its embedded link; decoded HTML out.

    The school's paging footer (page 1's response) carries anchors
    ``/menu1/dplycourse.asp?a=<server token>&<filter echo>&page=N``; the
    ``a`` token binds the result set to the page-1 session, so this GET must
    ride the SAME jar the captcha-spending POST used. No captcha is involved,
    so the request goes through the plain global lane (cap 2) like any other
    read. ``page_path`` is the root-relative href verbatim from the page -
    the adapter never constructs paging URLs itself (the school's parameter
    echo is authoritative).
    """
    async with build_client(cookies=cookies, transport=transport) as client:
        response = await request_school(
            client, "GET", f"{SELCRS_BASE_URL}{page_path}"
        )
    return _require_200(response, "dplycourse.asp?page")


async def get_write_form(
    cookies: httpx.Cookies,
    form_url: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    """GET (same session) the write form page (ssform/stage5 link from Studfun)."""
    async with build_client(cookies=cookies, transport=transport) as client:
        response = await request_school(client, "GET", form_url)
    return _require_200(response, "write form")


async def post_write(
    cookies: httpx.Cookies,
    submit_url: str,
    payload: dict[str, str],
    *,
    referer: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    """POST one submission (ssprs/saddstage5prs-style), Referer pinned.

    ``referer`` is MANDATORY and must be the same-session GET form URL the
    payload was replayed from (plan: write-path POST always carries
    ``Referer: <same-session GET form URL>``; the capture phase todo 4 will
    record whether the school hard-requires it - sent unconditionally here).
    ``payload`` is whitelisted earlier by the caller; this layer sends it
    verbatim and must never see a password field (adapter asserts none by
    construction - only the builder module in todo 14 creates payloads).
    """
    async with build_client(cookies=cookies, transport=transport) as client:
        response = await request_school(
            client, "POST", submit_url, data=payload, headers={"Referer": referer}
        )
    return _require_200(response, "write submit")
