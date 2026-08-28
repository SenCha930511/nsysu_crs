"""DB-backed catalog pipeline tests (plan todo 6, QA qa/06-partial.log).

DESTRUCTIVE OPT-IN (todo 17 hardening, debt b): every test here wipes the
WHOLE ``courses`` and ``ingest_runs`` tables (table-wide ``delete()``), so a
flagged run against the live compose DB erases the serving catalog. They are
therefore SKIPPED unless the operator explicitly sets
``CATALOG_DB_DESTRUCTIVE=1`` *and* a Postgres is reachable; assertions are
unchanged when opted in. Point ``DATABASE_URL`` at a scratch database for the
flagged run (see docs/runbook.md) - never run them flagged against the live
catalog.

Covers: full ingest happy path (2 scripted pages), upsert identity stability
across runs (same course id, quota counters refreshed), vanished-row
deletion, mid-run failure leaving the previous snapshot intact with
ok=false in the ledger, and the meta reader's shape.
"""

import os
import re
from pathlib import Path

import anyio
import httpx
import pytest
from sqlalchemy import delete, func, select

from app.catalog.ingest import run_ingest
from app.catalog.meta import latest_catalog_meta
from app.config import Settings
from app.db import build_engine, build_session_factory
from app.models.courses import Course, IngestRun
from app.selcrs.endpoints import ValidcodeResult
from app.selcrs.errors import SelcrsUnavailable
from app.solver.loop import CaptchaLoop

FIXTURES = Path(__file__).parent / "fixtures"


def _headers() -> list[str]:
    names = ["異動", "說明", "", "系所", "課號", "年級", "班別", "名稱", "學分",
             "期別", "必選", "限", "點", "上", "餘", "師", "室",
             "一", "二", "三", "四", "五", "六", "日", "備註", ""]
    return [f"<th>{name}</th>" for name in names]


def _course_row(short_id: str, dept: str, name_zh: str, teacher: str,
                room: str, slots: tuple[str, ...], credit: str = "3",
                comp: str = "必", quota: tuple[str, str, str, str] = ("60", "10", "8", "52")) -> str:
    cells = ["", "", "", dept, short_id, "1", "甲", f"{name_zh}<br>{name_zh} EN",
             credit, "期", comp, *quota, teacher, room, *slots, "", ""]
    return "<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>"


def _page(page_no: int, total: int, rows: list[str]) -> str:
    body = "".join(rows)
    header = "".join(_headers())
    # Live paging contract: a GET anchor to the next page (no re-POST).
    next_link = (
        f'<a href="/menu1/dplycourse.asp?a=t&D0=1151&DEG_COD=*&page={page_no + 1}">n</a>'
        if page_no < total
        else ""
    )
    return (
        f'<html><body><p>Showing page {page_no} of {total} pages</p>'
        f'<table><tr>{header}</tr>{body}</table>{next_link}</body></html>'
    )


SLOTS_A = ("12", "", "", "", "", "", "")
SLOTS_B = ("", "", "56", "", "", "", "")


def _three_row_pages() -> dict[int, str]:
    return {
        1: _page(1, 2, [
            _course_row("CSE101", "資訊工程學系", "程式設計(一)", "陳志明", "工EC5022", SLOTS_A),
            _course_row("CSE102", "資訊工程學系", "資料結構", "黃喆霖", "工EC5023", SLOTS_B),
        ]),
        2: _page(2, 2, [
            _course_row("GE204", "通識教育中心", "海洋與社會", "林育成", "海洋10F", SLOTS_A),
        ]),
    }


class _ScriptedSchool:
    """Loop seams: fake validcode issuer + per-page responder (or raiser)."""

    def __init__(self, pages: dict[int, str] | None = None,
                 fail_pages: set[int] | None = None) -> None:
        self.pages = pages or {}
        self.fail_pages = fail_pages or set()
        self.fetched_pages: list[int] = []

    async def validcode(self, *, cookies=None, transport=None) -> ValidcodeResult:
        return ValidcodeResult(image_bytes=b"not-a-bmp", cookies=httpx.Cookies())

    def factory(self, page_no: int):
        async def _fetch(query, *, validcode, cookies, transport=None):
            self.fetched_pages.append(page_no)
            if page_no in self.fail_pages:
                raise SelcrsUnavailable(f"scripted page-{page_no} outage")
            return self.pages[page_no]

        return _fetch

    async def get(self, cookies, path: str, *, transport=None) -> str:
        """Paging-GET seam for pages 2..N (URL parsed for its page param)."""
        match = re.search(r"[?&]page=(\d+)", path)
        assert match is not None, f"unexpected paging path: {path}"
        page_no = int(match.group(1))
        self.fetched_pages.append(page_no)
        if page_no in self.fail_pages:
            raise SelcrsUnavailable(f"scripted page-{page_no} outage")
        return self.pages[page_no]

    def loop_factory(self, page_fetcher):
        return CaptchaLoop(
            solve=lambda img: "1234",
            validcode_fetcher=self.validcode,
            catalog_page_fetcher=page_fetcher,
        )


def _taiwan_session_factory():
    settings = Settings()
    engine = build_engine(settings)
    return engine, build_session_factory(engine)


async def _reset_tables(session_factory) -> None:
    async with session_factory() as session, session.begin():
        await session.execute(delete(Course))
        await session.execute(delete(IngestRun))


def _db_available() -> bool:
    async def probe() -> bool:
        try:
            engine, _session_factory = _taiwan_session_factory()
            async with engine.connect():
                pass
            await engine.dispose()
            return True
        except OSError:
            return False

    return anyio.run(probe)


# Short-circuit order matters: without the flag there is no DB dial at all.
pytestmark = pytest.mark.skipif(
    os.environ.get("CATALOG_DB_DESTRUCTIVE") != "1" or not _db_available(),
    reason=(
        "destructive full-table wipes are opt-in: set CATALOG_DB_DESTRUCTIVE=1 "
        "AND provide a reachable Postgres (see module docstring)"
    ),
)


async def _with_db(body) -> None:
    """One event loop per test: engine, table reset, and body cohabit it.

    anyio.run creates a fresh loop per call; a shared engine fixture would
    bind pooled asyncpg connections to the reset loop and then fault the
    body's loop ("Future attached to a different loop").
    """
    engine, factory = _taiwan_session_factory()
    try:
        await _reset_tables(factory)
        await body(factory)
    finally:
        await engine.dispose()


def test_full_ingest_persists_snapshot_and_meta():
    async def go(session_factory):
        school = _ScriptedSchool(pages=_three_row_pages())
        report = await run_ingest(
            session_factory,
            loop_factory=school.loop_factory,
            fetcher_factory=school.factory,
            get_fetcher=school.get,
            d0="1151",
        )
        assert report.ok, report.error
        assert (report.pages_announced, report.pages_fetched) == (2, 2)
        assert report.rows_stored == 3
        # Only page 1 spends captcha (one accepted attempt); page 2 is a GET.
        assert report.captcha_attempts == 1
        assert school.fetched_pages == [1, 2]

        async with session_factory() as session:
            courses = (await session.execute(select(Course))).scalars().all()
            assert len(courses) == 3
            by_name = {course.name_zh: course for course in courses}
            assert "喆" in by_name["資料結構"].teacher  # HKSCS round-trips to PG
            assert by_name["程式設計(一)"].class_time == ["12", "", "", "", "", "", ""]
            assert by_name["程式設計(一)"].credit == 3
            assert by_name["海洋與社會"].compulsory is True

            run = (await session.execute(select(IngestRun))).scalars().one()
            assert run.ok is True
            assert run.rows == 3
            assert run.source == "self-scrape"
            assert run.error is None
            assert run.finished_at is not None

            meta = await latest_catalog_meta(session)
            assert meta is not None
            assert meta.ok is True
            assert meta.row_count == 3
            assert meta.source == "self-scrape"

    anyio.run(_with_db, go)


def test_second_run_updates_in_place_and_deletes_vanished():
    async def go(session_factory):
        pages = _three_row_pages()
        school_a = _ScriptedSchool(pages=pages)
        await run_ingest(
            session_factory, loop_factory=school_a.loop_factory,
            fetcher_factory=school_a.factory, get_fetcher=school_a.get, d0="1151",
        )

        pages_b = dict(pages)
        # quota moved on row 1; page 2 came back empty (both other rows vanished)
        pages_b[1] = _page(1, 2, [
            _course_row("CSE101", "資訊工程學系", "程式設計(一)", "陳志明", "工EC5022",
                        SLOTS_A, quota=("60", "99", "87", "0")),
        ])
        pages_b[2] = _page(2, 2, [])
        school_b = _ScriptedSchool(pages=pages_b)
        report = await run_ingest(
            session_factory, loop_factory=school_b.loop_factory,
            fetcher_factory=school_b.factory, get_fetcher=school_b.get, d0="1151",
        )
        assert report.ok and report.persist is not None
        assert report.persist.rows_updated == 1
        assert report.persist.rows_inserted == 0
        assert report.persist.rows_deleted == 2

        async with session_factory() as session:
            courses = (await session.execute(select(Course))).scalars().all()
            assert len(courses) == 1
            survivor = courses[0]
            assert survivor.name_zh == "程式設計(一)"
            assert (survivor.select_n, survivor.selected_n, survivor.remaining) == (99, 87, 0)

    anyio.run(_with_db, go)


def test_mid_run_failure_keeps_previous_snapshot():
    async def go(session_factory):
        # Given: one successful ingest round (the servable snapshot)
        school_ok = _ScriptedSchool(pages=_three_row_pages())
        good = await run_ingest(
            session_factory, loop_factory=school_ok.loop_factory,
            fetcher_factory=school_ok.factory, get_fetcher=school_ok.get, d0="1151",
        )
        assert good.ok

        async with session_factory() as session:
            before = (await session.execute(
                select(Course.name_zh, Course.select_n)
            )).all()

        # When: a later round dies on page 2 (beyond adapter retries)
        school_bad = _ScriptedSchool(pages=_three_row_pages(), fail_pages={2})
        bad = await run_ingest(
            session_factory, loop_factory=school_bad.loop_factory,
            fetcher_factory=school_bad.factory, get_fetcher=school_bad.get, d0="1151",
        )

        # Then: report + ledger say failed, previous rows untouched
        assert bad.ok is False
        assert "SelcrsUnavailable" in (bad.error or "")
        assert bad.pages_fetched == 1
        async with session_factory() as session:
            after = (await session.execute(
                select(Course.name_zh, Course.select_n)
            )).all()
            assert after == before, "failed round must not touch the snapshot"
            runs = (await session.execute(
                select(IngestRun).order_by(IngestRun.started_at)
            )).scalars().all()
            assert [run.ok for run in runs] == [True, False]
            assert runs[-1].error and "scripted page-2 outage" in runs[-1].error
            assert runs[-1].rows is None
            meta = await latest_catalog_meta(session)
            assert meta is not None and meta.ok is False

    anyio.run(_with_db, go)


def test_layout_break_aborts_without_touching_snapshot():
    async def go(session_factory):
        school_ok = _ScriptedSchool(pages=_three_row_pages())
        assert (await run_ingest(
            session_factory, loop_factory=school_ok.loop_factory,
            fetcher_factory=school_ok.factory, get_fetcher=school_ok.get, d0="1151",
        )).ok

        garbage = {1: _page(1, 1, [_course_row("X", "d", "n", "t", "r", ("",) * 7)
                                   .replace("<td>3</td>", "<td>THREE</td>", 1)])}
        school_bad = _ScriptedSchool(pages=garbage)
        report = await run_ingest(
            session_factory, loop_factory=school_bad.loop_factory,
            fetcher_factory=school_bad.factory, get_fetcher=school_bad.get, d0="1151",
        )
        assert report.ok is False
        assert "CatalogLayoutError" in (report.error or "")
        async with session_factory() as session:
            count = (await session.execute(select(func.count()).select_from(Course))).scalar_one()
            assert count == 3

    anyio.run(_with_db, go)


def test_duplicate_rows_within_one_scrape_dedup():
    async def go(session_factory):
        dup = _course_row("CSE101", "資訊工程學系", "程式設計(一)", "陳志明", "工EC5022", SLOTS_A)
        school = _ScriptedSchool(pages={1: _page(1, 1, [dup, dup])})
        report = await run_ingest(
            session_factory, loop_factory=school.loop_factory,
            fetcher_factory=school.factory, get_fetcher=school.get, d0="1151",
        )
        assert report.ok and report.persist is not None
        assert report.persist.dedup_skipped == 1
        assert report.rows_stored == 1

    anyio.run(_with_db, go)
