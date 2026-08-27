"""Captcha-parented catalog fetch loop (plan todo 5).

One page fetch = "fetch fresh BMP -> solve -> submit", repeated while the
school answers with a wrong-validation-code marker, at most
``MAX_SOLVE_ATTEMPTS`` (5) times; on the 5th rejection the loop raises
``CaptchaUnsolvable`` EXACTLY ONCE and never attempts a 6th (the gate's
terminal state, not a silent skip).

Marker contract: the dplycourse.asp response contains "Wrong Validation Code"
or 「驗證碼錯誤」 when the solved code was rejected. Matching uses the same
tolerance policy as sso2.py (NFKC fold + strip all whitespace, then substring
search) so alert()/meta-refresh wrappers and full/half-width variants cannot
hide the markers. A response WITHOUT a marker is a success by this layer's
definition - business parsing of the catalog rows belongs to todo 6.

Per-run cookie jar: each ``run_page`` call starts with NO jar, so
``fetch_validcode`` mints a fresh one; that jar then evolves along the run
(every retry refetches the BMP under the same per-run lineage, since the
captcha answer binds to the session it was issued to). Two overlapping runs
therefore never share a jar - asserted at THIS level in
tests/test_solver_loop.py - and every request still rides the adapter's
captcha semaphore=1 nested inside the global school cap of 2 (todo 3).

The solver callable is injectable (tests pass a fake; no ddddocr needed to
exercise the loop). OCR is CPU-bound and synchronous, so the loop offloads it
to a worker thread and never blocks the event loop.
"""

import unicodedata
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final

import anyio

from app.selcrs.endpoints import (
    CatalogQuery,
    ValidcodeResult,
    fetch_catalog_page,
    fetch_validcode,
)
from app.solver.errors import CaptchaUnsolvable
from app.solver.ocr import solve as _ddddocr_solve

MAX_SOLVE_ATTEMPTS: Final = 5
WRONG_CODE_MARKERS: Final = ("Wrong Validation Code", "驗證碼錯誤")

# Injectable seams. The fetchers default to the real adapter functions; tests
# substitute scripted fakes. ``transport`` is passed through verbatim - this
# package must not import httpx (adapter-boundary guardrail), so it is typed
# as a plain object here.
SolverFn = Callable[[bytes], str]
ValidcodeFetcher = Callable[..., Awaitable[ValidcodeResult]]
CatalogPageFetcher = Callable[..., Awaitable[str]]


def _normalize(text: str) -> str:
    """NFKC fold (full/half-width) and drop all whitespace; cf. sso2.py."""
    return "".join(unicodedata.normalize("NFKC", text).split())


_NORMALIZED_MARKERS: Final = tuple(_normalize(m) for m in WRONG_CODE_MARKERS)


def is_wrong_code_response(html: str) -> bool:
    """True iff the decoded dplycourse page carries a wrong-code marker."""
    normalized = _normalize(html)
    return any(marker in normalized for marker in _NORMALIZED_MARKERS)


@dataclass(frozen=True, slots=True)
class CaptchaPageResult:
    """One accepted catalog page.

    ``validcode`` is the attempt artifact whose code the school accepted; it
    carriers the run's cookie jar, which is how the jar-isolation contract is
    observed at this level (tests compare two concurrent runs' jars).
    """

    html: str
    attempts: int
    validcode: ValidcodeResult


class CaptchaLoop:
    """Retry loop for ONE captcha-parented catalog page fetch.

    The four constructor seams are independent injection points (OCR solver,
    two adapter fetchers, retry budget) used by tests to run the loop with a
    scripted school and a fake solver - not a bundle of related values.
    """

    def __init__(
        self,
        *,
        solve: SolverFn | None = None,
        validcode_fetcher: ValidcodeFetcher = fetch_validcode,
        catalog_page_fetcher: CatalogPageFetcher = fetch_catalog_page,
        max_attempts: int = MAX_SOLVE_ATTEMPTS,
    ) -> None:
        self._solve: Final = solve if solve is not None else _ddddocr_solve
        self._fetch_validcode: Final = validcode_fetcher
        self._fetch_catalog_page: Final = catalog_page_fetcher
        self._max_attempts: Final = max_attempts

    async def run_page(
        self, query: CatalogQuery, *, transport: object | None = None
    ) -> CaptchaPageResult:
        """Fetch one catalog page, retrying from a FRESH BMP per attempt.

        Raises ``CaptchaUnsolvable`` after the final wrong-code response.
        Transport/non-200 school anomalies from the adapter (``SelcrsUnavailable``)
        propagate unchanged - school-side failure, not solver failure.
        """
        jar: object | None = None  # per-run; first fetch mints it fresh
        for attempt in range(1, self._max_attempts + 1):
            validcode = await self._fetch_validcode(cookies=jar, transport=transport)
            jar = validcode.cookies  # evolve the run's jar lineage
            code = await anyio.to_thread.run_sync(self._solve, validcode.image_bytes)
            html = await self._fetch_catalog_page(
                query, validcode=code, cookies=jar, transport=transport
            )
            if not is_wrong_code_response(html):
                return CaptchaPageResult(
                    html=html, attempts=attempt, validcode=validcode
                )
        raise CaptchaUnsolvable(attempts=self._max_attempts)


__all__ = [
    "MAX_SOLVE_ATTEMPTS",
    "WRONG_CODE_MARKERS",
    "CaptchaLoop",
    "CaptchaPageResult",
    "is_wrong_code_response",
]
