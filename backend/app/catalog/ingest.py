"""Catalog ingest pipeline (plan todo 6).

Flow: open an ingest_runs ledger row -> discover the current year-semester
code D0 (qrycourse ``YRSM``) -> fetch page 1 of the full catalog
(``DEG_COD=*``) through the solver's captcha loop -> pages 2..N by GETting
the paging footer links embedded in each response
(``/menu1/dplycourse.asp?a=<token>&...&page=N``; live-verified paging
contract 2026-08-28: the ``a`` token binds the result set to the page-1
session, so the GETs reuse the page-1 jar, no captcha is spent, plain global
lane) -> parse rows -> replace the semester snapshot in ONE transaction ->
close the ledger ok=true.

Failure contract: any SelcrsUnavailable / CaptchaUnsolvable / layout break /
missing paging link / DB error aborts BEFORE the snapshot transaction
commits - the previous snapshot stays servable and the ledger closes
ok=false with the error text (plan: 失敗沿用前快照). "Every candidate row on
every page failed acceptance" is treated as a layout break (parse rules
silently disagreeing with reality), not as a legitimately empty catalog.

Seams (tests, QA scripts): the solver loop, the discovery fetcher, the
page-1 fetcher factory, and the paging GET fetcher are all injectable;
production uses the real adapter-backed defaults.
"""

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.catalog.discover import discover_current_d0
from app.catalog.parse import (
    ParsedCatalogPage,
    extract_page_link,
    parse_catalog_page,
)
from app.catalog.persist import (
    PersistOutcome,
    close_ingest_run,
    open_ingest_run,
    replace_year_sem_snapshot,
)
from app.catalog.rows import CatalogRow
from app.selcrs.endpoints import (
    CatalogQuery,
    fetch_catalog_page,
    fetch_catalog_page_get,
)
from app.selcrs.errors import SelcrsError
from app.solver.errors import CaptchaUnsolvable
from app.solver.loop import CaptchaLoop

#: Full catalog = every degree program (plan todo 6 field contract).
DEG_COD_ALL: Final = "*"

#: Thin wrapper matching CaptchaLoop's catalog_page_fetcher call shape:
#: (query, validcode=, cookies=, transport=); the page number is bound by the
#: factory below. Returned value is the decoded page HTML.
PageFetcher = Callable[..., Awaitable[str]]
PageFetcherFactory = Callable[[int], PageFetcher]


def default_page_fetcher_factory(page: int) -> PageFetcher:
    """Production page-1 fetcher: the adapter's captcha-spending POST.

    ``page`` is kept for call-shape symmetry only: the school's real paging
    contract never re-POSTs, so this factory is used for page 1 alone.
    """

    async def _fetch(
        query: CatalogQuery,
        *,
        validcode: str,
        cookies: object,
        transport: object | None = None,
    ) -> str:
        return await fetch_catalog_page(
            query,
            validcode=validcode,
            cookies=cookies,  # type: ignore[arg-type]  # loop passes httpx.Cookies
            transport=transport,  # type: ignore[arg-type]
        )

    return _fetch


#: Pages 2..N live-fetch: (cookies, root-relative paging path) -> decoded HTML.
GetFetcher = Callable[..., Awaitable[str]]


#: Builds the solver loop for one page fetch. Tests substitute a scripted
#: loop (fake solver/fetchers) here instead of touching CaptchaLoop internals.
LoopFactory = Callable[[PageFetcher], CaptchaLoop]


def default_loop_factory(page_fetcher: PageFetcher) -> CaptchaLoop:
    """Production loop: real ddddocr solver + real adapter fetchers."""
    return CaptchaLoop(catalog_page_fetcher=page_fetcher)


class CatalogLayoutError(Exception):
    """Parse rules silently disagreeing with reality (all candidates failed)."""


class CatalogPagingError(Exception):
    """A mid-run page carried no paging link for the next page - the school's
    response shape changed or the run's session lost its paged result set."""


@dataclass(frozen=True, slots=True)
class PageRecord:
    """Per-page ingest telemetry (QA logs + facts doc)."""

    page: int
    attempts: int
    seconds: float
    rows: int
    skipped: int


@dataclass(frozen=True, slots=True)
class IngestReport:
    """What one ingest round did. ``ok=False`` rounds carry ``error`` and
    never touched the snapshot; telemetry up to the failure is preserved."""

    year_sem: str | None
    ok: bool
    pages_announced: int | None
    pages_fetched: int
    rows_stored: int
    rows_skipped: int
    persist: PersistOutcome | None
    wall_seconds: float
    captcha_attempts: int
    error: str | None
    page_records: tuple[PageRecord, ...] = field(default_factory=tuple)

    @property
    def captcha_attempt_rate(self) -> float | None:
        """Per-attempt solver success rate p (accepted / submissions); the
        single captcha-parented page-1 fetch means accepted == 1 on success."""
        if self.captcha_attempts == 0:
            return None
        return 1.0 / self.captcha_attempts


def _fetch_all(
    parsed_pages: list[ParsedCatalogPage],
) -> list[CatalogRow]:
    return [row for parsed in parsed_pages for row in parsed.rows]


async def _fetch_first_page(
    loop_factory: LoopFactory,
    fetcher_factory: PageFetcherFactory,
    query: CatalogQuery,
) -> tuple[str, int, object, float]:
    """Page 1 through the captcha loop: (html, attempts, jar, seconds).

    The returned jar is the per-run session lineage that solved the captcha;
    paging GETs for pages 2..N MUST reuse it (the school binds the result
    set's ``a`` token to that session).
    """
    loop = loop_factory(fetcher_factory(1))
    started = time.monotonic()
    result = await loop.run_page(query)
    return result.html, result.attempts, result.validcode.cookies, time.monotonic() - started


async def run_ingest(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    loop_factory: LoopFactory | None = None,
    fetcher_factory: PageFetcherFactory = default_page_fetcher_factory,
    get_fetcher: GetFetcher = fetch_catalog_page_get,
    d0: str | None = None,
    discover: Callable[..., Awaitable[str]] = discover_current_d0,
) -> IngestReport:
    """Run one full ingest round. NEVER raises for school/solver/parse/DB
    failures - they land in the ledger + report instead (the scheduler must
    keep ticking; the snapshot policy is what callers rely on)."""
    active_loop_factory = loop_factory if loop_factory is not None else default_loop_factory
    run_id = await open_ingest_run(session_factory)
    started = time.monotonic()
    page_records: list[PageRecord] = []
    year_sem: str | None = None
    pages_announced: int | None = None
    parsed_pages: list[ParsedCatalogPage] = []
    persist_outcome: PersistOutcome | None = None

    async def _fail(error: str) -> IngestReport:
        await close_ingest_run(
            session_factory,
            run_id,
            ok=False,
            rows=None,
            error=error,
        )
        return IngestReport(
            year_sem=year_sem,
            ok=False,
            pages_announced=pages_announced,
            pages_fetched=len(page_records),
            rows_stored=0,
            rows_skipped=sum(record.skipped for record in page_records),
            persist=None,
            wall_seconds=time.monotonic() - started,
            # Only page 1 is captcha-parented (paging GETs spend no captcha);
            # PageRecord.attempts on later pages is the GET round-trip count,
            # always 1, and never belongs in this sum.
            captcha_attempts=page_records[0].attempts if page_records else 0,
            error=error,
            page_records=tuple(page_records),
        )

    try:
        year_sem = d0 if d0 is not None else await discover()
        query = CatalogQuery(year_sem=year_sem, deg_cod=DEG_COD_ALL)

        html, attempts, jar, seconds = await _fetch_first_page(
            active_loop_factory, fetcher_factory, query
        )
        first = parse_catalog_page(html, year_sem=year_sem)
        parsed_pages.append(first)
        page_records.append(
            PageRecord(1, attempts, seconds, len(first.rows), first.skipped_rows)
        )
        pages_announced = first.pagination.total if first.pagination else 1

        current_html = html
        for page_number in range(2, pages_announced + 1):
            link = extract_page_link(current_html, page_number)
            if link is None:
                raise CatalogPagingError(
                    f"page {page_number - 1} carried no paging link for page "
                    f"{page_number} (of {pages_announced})"
                )
            get_started = time.monotonic()
            html = await get_fetcher(jar, link)
            seconds = time.monotonic() - get_started
            parsed = parse_catalog_page(html, year_sem=year_sem)
            parsed_pages.append(parsed)
            page_records.append(
                PageRecord(page_number, 1, seconds, len(parsed.rows), parsed.skipped_rows)
            )
            current_html = html

        rows = _fetch_all(parsed_pages)
        total_candidates = sum(page.candidate_rows for page in parsed_pages)
        if not rows and total_candidates > 0:
            raise CatalogLayoutError(
                f"0 rows accepted out of {total_candidates} candidate rows "
                f"across {len(parsed_pages)} pages - layout changed?"
            )

        async with session_factory() as session, session.begin():
            persist_outcome = await replace_year_sem_snapshot(
                session, year_sem, rows
            )
    except (SelcrsError, CaptchaUnsolvable) as exc:
        return await _fail(f"{type(exc).__name__}: {exc}")
    except Exception as exc:  # noqa: BLE001 - the ledger must swallow, truthfully
        return await _fail(f"{type(exc).__name__}: {exc}")

    await close_ingest_run(
        session_factory,
        run_id,
        ok=True,
        rows=persist_outcome.rows_stored,
        error=None,
    )
    return IngestReport(
        year_sem=year_sem,
        ok=True,
        pages_announced=pages_announced,
        pages_fetched=len(page_records),
        rows_stored=persist_outcome.rows_stored,
        rows_skipped=sum(record.skipped for record in page_records),
        persist=persist_outcome,
        wall_seconds=time.monotonic() - started,
        captcha_attempts=page_records[0].attempts if page_records else 0,
        error=None,
        page_records=tuple(page_records),
    )
