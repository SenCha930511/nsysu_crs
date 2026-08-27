"""Endpoint wiring invariants (non-SSO2): paths, jar usage, empty Chinese
fields, mandatory Referer on the write path, and 200-or-unavailable rule."""

import urllib.parse

import httpx
import pytest

from app.selcrs.endpoints import (
    CatalogQuery,
    fetch_catalog_page,
    fetch_validcode,
    get_slt_result,
    get_studfun,
    get_write_form,
    post_write,
)
from app.selcrs.errors import SelcrsUnavailable
from tests.conftest import StubTransport


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _ok_body() -> bytes:
    return "<html><body>資料 資料</body></html>".encode("big5hkscs")


def _posted_form(body: bytes) -> dict[str, list[str]]:
    return urllib.parse.parse_qs(body.decode("ascii"), keep_blank_values=True)


@pytest.mark.anyio
async def test_fetch_validcode_hits_menu1_with_epoch_and_returns_fresh_bytes() -> None:
    # Given a school serving a BMP
    transport = StubTransport(
        lambda request: _async_response(request, b"BM-binary-not-decoded")
    )

    # When a captcha is fetched with a fixed epoch
    result = await fetch_validcode(epoch=1756200000000, transport=transport)

    # Then the request went to menu1/validcode.asp with that epoch
    request = transport.requests[0]
    assert request.method == "GET"
    assert request.url.path == "/menu1/validcode.asp"
    assert request.url.params["epoch"] == "1756200000000"
    # And the binary body came back untouched (never Big5-decoded)
    assert result.image_bytes == b"BM-binary-not-decoded"


@pytest.mark.anyio
async def test_fetch_validcode_status_errors_raise_unavailable() -> None:
    transport = StubTransport(lambda request: _async_response(request, b"", status=404))
    with pytest.raises(SelcrsUnavailable):
        await fetch_validcode(transport=transport)


@pytest.mark.anyio
async def test_catalog_post_hard_clears_chinese_fields_and_carries_contract_fields() -> None:
    transport = StubTransport(lambda request: _async_response(request, _ok_body()))
    jar = httpx.Cookies()
    jar.set("ASPSESSION", "seeded")

    await fetch_catalog_page(
        CatalogQuery(year_sem="1151", d1="11"),
        validcode="4242",
        cookies=jar,
        transport=transport,
    )

    request = transport.requests[0]
    assert request.method == "POST"
    assert request.url.path == "/menu1/dplycourse.asp"
    # The caller's jar rode along (captcha answer binds to this session)
    assert "ASPSESSION=seeded" in request.headers.get("cookie", "")
    form = _posted_form(request.content)
    # Chinese-text fields are pinned empty and cannot be passed through
    assert form["teacher"] == [""]
    assert form["crsname"] == [""]
    # Contract field set from the plan
    assert form["D0"] == ["1151"]
    assert form["D1"] == ["11"]
    assert form["TYP"] == ["1"]
    assert form["nowhis"] == ["1"]
    assert form["ValidCode"] == ["4242"]


@pytest.mark.anyio
async def test_post_write_always_sends_referer_of_same_session_form_url() -> None:
    transport = StubTransport(lambda request: _async_response(request, _ok_body()))
    form_url = "https://selcrs.nsysu.edu.tw/menu4/ssform.asp?X1=1"
    submit_url = "https://selcrs.nsysu.edu.tw/menu4/ssprs.asp"

    await post_write(
        httpx.Cookies(),
        submit_url,
        {"D1": "+", "C1": "12345678", "send": "提交"},
        referer=form_url,
        transport=transport,
    )

    request = transport.requests[0]
    assert request.headers["referer"] == form_url
    form = _posted_form(request.content)
    # Payload is replayed verbatim by this layer (builder lives in todo 14)
    assert form["C1"] == ["12345678"]
    # Non-ASCII form values are percent-encoded utf-8 by httpx; decode check:
    assert urllib.parse.unquote(request.content.decode("ascii")).count("提交") == 1


@pytest.mark.anyio
@pytest.mark.parametrize("status", (302, 404, 500))
async def test_page_endpoints_treat_non_200_as_school_anomaly(status: int) -> None:
    transport = StubTransport(
        lambda request: _async_response(request, b"moved or broken", status=status)
    )
    with pytest.raises(SelcrsUnavailable):
        await get_studfun(httpx.Cookies(), transport=transport)
    with pytest.raises(SelcrsUnavailable):
        await get_write_form(
            httpx.Cookies(),
            "https://selcrs.nsysu.edu.tw/menu4/ssform.asp?X1=1",
            transport=transport,
        )


@pytest.mark.anyio
async def test_get_studfun_returns_decoded_big5hkscs_body() -> None:
    transport = StubTransport(lambda request: _async_response(request, _ok_body()))
    html = await get_studfun(httpx.Cookies(), transport=transport)
    assert "資料" in html
    assert transport.requests[0].url.path == "/menu4/Studfun.asp"


@pytest.mark.anyio
async def test_get_slt_result_hits_query_path() -> None:
    transport = StubTransport(lambda request: _async_response(request, _ok_body()))
    await get_slt_result(httpx.Cookies(), transport=transport)
    assert transport.requests[0].url.path == "/menu4/query/slt_result.asp"


async def _async_response(
    request: httpx.Request, body: bytes, *, status: int = 200
) -> httpx.Response:
    if status == 302:
        return httpx.Response(302, content=body, headers={"Location": "/elsewhere"})
    return httpx.Response(status, content=body)
