"""Encoding-fix QA demo: fixture -> detected charset -> classification table.

Rows: the three 115-1 live captures + the synthetic Big5-era SSO2 fail
fixture. SSO2 pages are classified through the real tri-state classifier;
page fixtures are verified to decode cleanly (expected heading present, no
U+FFFD). This table is appended to qa/03-encoding.log.

``--probe-catalog`` additionally performs ONE live, PUBLIC catalog probe -
a single POST to the public dplycourse.asp endpoint with a deliberately
wrong ValidCode (no login, no captcha spent, no state change; the school
answers with its error page) - and records the response's detected charset,
HTTP status and byte size for docs/verified-facts.md. One request, never
more (do-not-hammer rule).

Usage:
    cd backend && uv run python -m scripts.encoding_demo [--probe-catalog]

Exit codes: 0 = table printed (probe outcome is recorded either way, it is
observational); 3 = probe aborted by a school-side transport anomaly.
"""

import argparse
import sys
from pathlib import Path
from typing import Final

import anyio
import httpx

from app.selcrs.decode import decode_body, resolve_charset
from app.selcrs.endpoints import SELCRS_BASE_URL, CatalogQuery, _catalog_form
from app.selcrs.errors import SelcrsUnavailable
from app.selcrs.http import build_client, request_school
from app.selcrs.sso2 import classify_sso2_response

FIXTURES_DIR: Final = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

_SSO2_FIXTURES: Final = (
    "sso2_fail_live_1151.html",
    "sso2_fail_big5_synthetic.html",
)
_PAGE_FIXTURES: Final = (
    ("slt_result_live_1151.html", "課程名稱"),
    ("studfun_closed_live_1151.html", "選課關閉"),
)


def _classify_sso2_fixture(raw: bytes) -> str:
    response = httpx.Response(200, content=raw)
    try:
        return f"SSO2 {classify_sso2_response(response).value.upper()}"
    except SelcrsUnavailable:
        return "SSO2 UNKNOWN (SelcrsUnavailable)"


def _fixture_rows() -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for name in _SSO2_FIXTURES:
        raw = (FIXTURES_DIR / name).read_bytes()
        rows.append((name, resolve_charset(raw), _classify_sso2_fixture(raw)))
    for name, expected_heading in _PAGE_FIXTURES:
        raw = (FIXTURES_DIR / name).read_bytes()
        text = decode_body(raw)
        classification = (
            f"page decode OK ('{expected_heading}' present, no U+FFFD)"
            if expected_heading in text and "\ufffd" not in text
            else f"page decode SUSPECT (expect '{expected_heading}')"
        )
        rows.append((name, resolve_charset(raw), classification))
    return rows


async def _probe_catalog() -> None:
    """One public catalog POST with a deliberately wrong ValidCode.

    The school's refusal page is still the dplycourse.asp pipeline responding,
    which is exactly what the charset record needs. No login, no captcha
    solve, no query executed school-side.
    """
    jar = httpx.Cookies()
    async with build_client(cookies=jar) as client:
        response = await request_school(
            client,
            "POST",
            f"{SELCRS_BASE_URL}/menu1/dplycourse.asp",
            data=_catalog_form(CatalogQuery(year_sem="1151"), "0000"),
            captcha_parented=True,
        )
    charset = resolve_charset(response.content, response.headers.get("content-type"))
    print(
        "catalog probe: POST /menu1/dplycourse.asp "
        "(public, deliberately-wrong ValidCode=0000, ONE request)"
    )
    print(f"  -> HTTP {response.status_code}, {len(response.content)} bytes")
    print(f"  -> content-type: {response.headers.get('content-type', '<absent>')}")
    print(f"  -> detected charset: {charset}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--probe-catalog",
        action="store_true",
        help="run the ONE-request live public catalog charset probe",
    )
    args = parser.parse_args()

    rows = _fixture_rows()
    name_width = max(len(name) for name, _, _ in rows)
    charset_width = max(len(charset) for _, charset, _ in rows)
    print(f"{'fixture':<{name_width}}  {'detected':<{charset_width}}  classification")
    print(f"{'-' * name_width}  {'-' * charset_width}  {'-' * 40}")
    for name, charset, classification in rows:
        print(f"{name:<{name_width}}  {charset:<{charset_width}}  {classification}")

    if args.probe_catalog:
        try:
            anyio.run(_probe_catalog)
        except SelcrsUnavailable as exc:
            print(f"catalog probe: UNVERIFIED - transport anomaly ({exc.detail})")
            return 3
    else:
        print("catalog probe: skipped (pass --probe-catalog for the ONE live request)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
