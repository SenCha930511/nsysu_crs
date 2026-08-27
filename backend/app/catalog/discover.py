"""Catalog discovery: qrycourse.asp's ``<select id="YRSM">`` -> current D0.

The YRSM <select> lists the academic year-semester codes the catalog accepts
(e.g. "1132", "1141", "1142", "1151"). The current one is the option the page
pre-selects; when none carries a ``selected`` attribute we take the
numerically greatest 4-digit code (codes are YYY+S, monotonic in time).

Fetching rides the adapter (``fetch_qrycourse`` - plain global lane, no
captcha); it is injectable so tests never touch the school.
"""

import re
from collections.abc import Awaitable, Callable
from typing import Final

from bs4 import BeautifulSoup

from app.selcrs.endpoints import fetch_qrycourse

_SELECT_ID: Final = "YRSM"
_D0_RE: Final = re.compile(r"^\d{4}$")

QrycourseFetcher = Callable[..., Awaitable[str]]


class DiscoveryError(Exception):
    """The discovery page did not yield a usable YRSM <select>."""


def parse_d0_options(html: str) -> tuple[str, ...]:
    """All 4-digit year-semester option values on the discovery page."""
    soup = BeautifulSoup(html, "html.parser")
    select = soup.find("select", id=_SELECT_ID)
    if select is None:
        raise DiscoveryError(f'qrycourse page has no <select id="{_SELECT_ID}">')
    options: list[str] = []
    for option in select.find_all("option"):
        value = option.get("value")
        candidate = (value if isinstance(value, str) else option.get_text()).strip()
        if _D0_RE.match(candidate):
            options.append(candidate)
    if not options:
        raise DiscoveryError(
            f'qrycourse <select id="{_SELECT_ID}"> has no 4-digit options'
        )
    return tuple(options)


def pick_current_d0(html: str) -> str:
    """The current year-semester code: the pre-selected option, else the max."""
    soup = BeautifulSoup(html, "html.parser")
    select = soup.find("select", id=_SELECT_ID)
    if select is None:
        raise DiscoveryError(f'qrycourse page has no <select id="{_SELECT_ID}">')
    for option in select.find_all("option", selected=True):
        value = option.get("value")
        candidate = (value if isinstance(value, str) else option.get_text()).strip()
        if _D0_RE.match(candidate):
            return candidate
    return max(parse_d0_options(html), key=int)


async def discover_current_d0(
    *, fetcher: QrycourseFetcher = fetch_qrycourse
) -> str:
    """Fetch the discovery page through the adapter and pick the current D0."""
    return pick_current_d0(await fetcher())
