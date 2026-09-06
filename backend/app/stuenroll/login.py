"""Interactive login flow for stu_enroll-family subsystems (M1).

Shared shape, live-proven on both stu_enroll and sco during M0: GET the login
page, then spend attempts; each attempt fetches a fresh captcha BMP on the
same jar lineage, POSTs the form with verbatim hidden fields plus the
id/password/captcha overrides, and classifies the answer. A wrong-code marker
spends another attempt; anything else hands straight into the chain walker -
the school's own handoff/redirect relay decides what shape the landing really
is, never this module's guesses.
"""

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final
from urllib.parse import urljoin

import anyio

from app.selcrs.decode import decode_body
from app.selcrs.errors import SelcrsUnavailable
from app.selcrs.http import AsyncBaseTransport, Cookies
from app.stuenroll.classify import LoginVerdict, classify_login_response
from app.stuenroll.endpoints import PageResult, fetch_validcode, get_page, post_form
from app.stuenroll.fields import scrape_page
from app.stuenroll.handoff import ChainResult, walk_chain

MAX_LOGIN_ATTEMPTS: Final = 5
MAX_CAPTCHA_FETCHES_PER_ATTEMPT: Final = 4
_CODE_4DIGIT_RE: Final = re.compile(r"^\d{4}$")

SolveFn = Callable[[bytes], str]


@dataclass(frozen=True, slots=True)
class FieldRoles:
    """Which form fields receive the id / password / captcha answer."""

    id_names: tuple[str, ...]
    password_names: tuple[str, ...]
    validcode_name: str


STU_ENROLL_ROLES: Final = FieldRoles(
    id_names=("IDtmp", "ID"), password_names=("passwdtmp", "passwd"), validcode_name="ValidCode"
)
SCO_ROLES: Final = FieldRoles(
    id_names=("SID",), password_names=("PASSWD",), validcode_name="ValidCode"
)


@dataclass(frozen=True, slots=True)
class LoginOutcome:
    """One interactive-login round: final landing (when ok) + attempt forensics."""

    ok: bool
    landing: ChainResult | None
    attempts: int
    captcha_rejects: int


def _default_solve() -> SolveFn:
    """Late binding keeps the package importable without ddddocr present."""
    from app.solver.ocr import solve

    return solve


async def interactive_login(
    student_id: str,
    password: str,
    *,
    roles: FieldRoles,
    login_url: str,
    solve: SolveFn | None = None,
    transport: AsyncBaseTransport | None = None,
) -> LoginOutcome:
    """Log in to one subsystem and follow the resulting relay chain to content.

    Returns ``ok=False`` when the captcha budget is exhausted before any
    answer clears the system's own verification. School-side shape drifts
    (missing form, dead captcha endpoint) raise SelcrsUnavailable - that is
    breaker input, not a wrong credential.
    """
    ocr = solve if solve is not None else _default_solve()
    first = await get_page(login_url, None, transport=transport)
    jar = first.cookies
    form = scrape_page(decode_body(first.content, first.content_type))
    if form.action is None or not any(type_ == "password" for _n, type_, _v in form.inputs):
        raise SelcrsUnavailable(f"{login_url} carries no interactive login form")
    post_url = urljoin(login_url, form.action)
    captcha_base = (
        urljoin(login_url, form.captcha_srcs[0]).split("?")[0] if form.captcha_srcs else None
    )

    overrides_seed = {
        **{name: student_id for name in roles.id_names},
        **{name: password for name in roles.password_names},
    }
    rejects = 0
    response: PageResult | None = None
    attempt = 0
    for attempt in range(1, MAX_LOGIN_ATTEMPTS + 1):
        code = ""
        if captcha_base is not None:
            for _fetch in range(MAX_CAPTCHA_FETCHES_PER_ATTEMPT):
                stamp = int(time.time() * 1000)
                bmp, jar = await fetch_validcode(f"{captcha_base}?epoch={stamp}", jar)
                code = await anyio.to_thread.run_sync(ocr, bmp)
                if _CODE_4DIGIT_RE.match(code) is not None:
                    break
        overrides = dict(overrides_seed)
        if code:
            overrides[roles.validcode_name] = code
        pairs = tuple(
            (name, overrides.get(name, value)) for name, _type, value in form.inputs
        )
        response = await post_form(post_url, pairs, jar, referer=login_url, transport=transport)
        jar = response.cookies
        if response.status_code in (301, 302, 303):
            break
        verdict = classify_login_response(decode_body(response.content, response.content_type))
        if verdict is LoginVerdict.CAPTCHA_FAIL:
            rejects += 1
            continue
        break
    if response is None or (
        response.status_code not in (301, 302, 303)
        and classify_login_response(decode_body(response.content, response.content_type))
        is LoginVerdict.CAPTCHA_FAIL
    ):
        return LoginOutcome(ok=False, landing=None, attempts=attempt, captcha_rejects=rejects)

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
        start_status=response.status_code,
        start_content=response.content,
        start_url=post_url,
        start_location=response.location,
        start_content_type=response.content_type,
        jar=jar,
    )
    return LoginOutcome(ok=True, landing=landing, attempts=attempt, captcha_rejects=rejects)
