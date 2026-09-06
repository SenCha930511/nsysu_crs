"""Handoff detection + the interleaved handoff/redirect chain walker (M1).

The school's login ceremonies are NOT single posts: each subsystem answers
with a tiny auto-submit form page forwarding the credentials to the next
endpoint, and GET redirects interleave between hops (proven shapes across
stu_enroll -> wregloginchk -> wregloginchk2 -> 302 main; verify ssn1/idno hop;
tfstu relay hop; sco Studpassform hop; enrollcert button relay hop).

A page counts as a HANDOFF only when it is all of:

- small (< ``_HANDOFF_MAX_BYTES`` - the big interactive login forms never are),
- carrying a ``.<formname>.submit()`` auto-post script, and
- its form has an action and ONLY hidden inputs.

That structure is the classifier: marker-text heuristics fail here (handoff
pages carry the ``ValidCode`` field name, which blew up a "still on the login
form" check during M0).
"""

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final
from urllib.parse import urljoin

from app.selcrs.http import Cookies
from app.stuenroll.fields import scrape_page

HANDOFF_MAX_BYTES: Final = 2048
DEFAULT_MAX_HOPS: Final = 4
DEFAULT_MAX_REDIRECTS: Final = 4

_SUBMIT_SCRIPT_RE: Final = re.compile(r"\.\s*submit\s*\(\s*\)")


@dataclass(frozen=True, slots=True)
class HandoffForm:
    """One auto-submit credential forward: where to POST and the verbatim fields."""

    action: str
    fields: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class ChainResult:
    """End of a chain walk: last response plus forensics for ledgers/tests."""

    status_code: int
    content: bytes
    content_type: str | None
    url: str
    hops: int
    redirects: int
    cookies: Cookies | None


def read_handoff(html_text: str) -> HandoffForm | None:
    """The handoff form on one page, or None when the page is not a handoff."""
    page = scrape_page(html_text)
    if (
        page.action is None
        or _SUBMIT_SCRIPT_RE.search(html_text) is None
        or not page.inputs
        or any(type_ != "hidden" for _name, type_, _value in page.inputs)
    ):
        return None
    return HandoffForm(
        action=page.action,
        fields=tuple((name, value) for name, _type, value in page.inputs),
    )


from app.stuenroll.endpoints import PageResult

#: GET hop: (url, jar) -> page with the evolved jar inside
GetFn = Callable[[str, "Cookies | None"], Awaitable[PageResult]]
#: POST hop: (url, fields, jar, referer) -> page with the evolved jar inside
PostFn = Callable[
    [str, tuple[tuple[str, str], ...], "Cookies | None", str],
    Awaitable[PageResult],
]
DecodeFn = Callable[[bytes], str]


async def walk_chain(
    *,
    get: GetFn,
    post: PostFn,
    decode: DecodeFn,
    start_status: int,
    start_content: bytes,
    start_url: str,
    start_location: str | None = None,
    start_content_type: str | None = None,
    jar: "Cookies | None" = None,
    max_hops: int = DEFAULT_MAX_HOPS,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
) -> ChainResult:
    """Walk one handoff/redirect chain to its content page.

    ``decode`` is the adapter's bytes->str policy (big5hkscs-aware); both hop
    callables return PageResult so the caller threads the jar lineage through
    the walk (invariant 1 in the package docstring). Bounded separately on
    handoffs and redirects: the chain ends at the first response that is
    neither a redirect nor a handoff - that is the content page, verbatim.
    """
    status, content, url = start_status, start_content, start_url
    location, content_type, hops, redirects = start_location, start_content_type, 0, 0
    while True:
        if status in (301, 302, 303) and location and redirects < max_redirects:
            url = urljoin(url, location)
            page = await get(url, jar)
            status, content, content_type, location, jar = (
                page.status_code,
                page.content,
                page.content_type,
                page.location,
                page.cookies,
            )
            redirects += 1
            continue
        if hops >= max_hops or len(content) >= HANDOFF_MAX_BYTES:
            break
        form = read_handoff(decode(content))
        if form is None:
            break
        hops += 1
        target = urljoin(url, form.action)
        page = await post(target, form.fields, jar, url)
        url = target
        status, content, content_type, location, jar = (
            page.status_code,
            page.content,
            page.content_type,
            page.location,
            page.cookies,
        )
    return ChainResult(
        status_code=status,
        content=content,
        content_type=content_type,
        url=url,
        hops=hops,
        redirects=redirects,
        cookies=jar,
    )
