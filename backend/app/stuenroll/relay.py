"""Relay opener for the regweb family: act=71 GET + chain walk + bounce detect.

A dead jar bounces the relay back to an interactive login page - detected by
the landing page carrying a password input (both live login pages in M0 do;
the tfstudata / regweb-main / pdf landings never do). A bounce maps to
SelcrsSessionExpired so API layers answer the family's own 401; other shape
drift surfaces as SelcrsUnavailable from the IO layer below.
"""

from app.selcrs.decode import decode_body
from app.selcrs.errors import SelcrsSessionExpired
from app.selcrs.http import AsyncBaseTransport, Cookies
from app.stuenroll.endpoints import PageResult, get_page, post_form
from app.stuenroll.fields import scrape_page
from app.stuenroll.handoff import ChainResult, walk_chain


async def open_relay(
    start_url: str,
    jar: Cookies | None,
    *,
    transport: AsyncBaseTransport | None = None,
) -> ChainResult:
    """GET ``start_url`` and walk the school's handoff/redirect chain to the
    final landing. Raises SelcrsSessionExpired when the relay bounced to an
    interactive login page; everything else lands on whatever the school sent.
    """
    first = await get_page(start_url, jar, transport=transport)

    async def _get(url: str, jar_in: Cookies | None) -> PageResult:
        return await get_page(url, jar_in, transport=transport)

    async def _post(
        url: str, fields: tuple[tuple[str, str], ...], jar_in: Cookies | None, referer: str
    ) -> PageResult:
        return await post_form(url, fields, jar_in, referer=referer, transport=transport)

    landing = await walk_chain(
        get=_get,
        post=_post,
        decode=lambda raw: decode_body(raw, None),
        start_status=first.status_code,
        start_content=first.content,
        start_url=start_url,
        start_location=first.location,
        start_content_type=first.content_type,
        jar=first.cookies,
    )
    html = decode_body(landing.content, landing.content_type)
    if any(_type == "password" for _name, _type, _value in scrape_page(html).inputs):
        raise SelcrsSessionExpired("relay bounced to an interactive login page")
    return landing
