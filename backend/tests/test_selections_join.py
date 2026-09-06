"""attach_course_matches - catalog join enrich coverage.

Existing selections API tests monkeypatch the join away (stub_attach), so the
real join had no direct coverage. This file pins the enrich contract: url +
course_id both come from the catalog row for the same code; unmatched rows get
unknown=True and url=None. Mirrors test_query_api.py's live-Compose-Postgres
harness (skipped when compose Postgres is unreachable).
"""

import anyio
import pytest
from sqlalchemy import delete

from app.config import Settings
from app.db import build_engine, build_session_factory
from app.models.courses import Course
from app.selections.join import attach_course_matches
from app.selections.parse import SelectionItem

TEST_YEAR_SEM = "1151"
SEED_CODE = "CSE515"


def _engine_factory():
    engine = build_engine(Settings())
    return engine, build_session_factory(engine)


async def _wipe(factory) -> None:
    async with factory() as session, session.begin():
        await session.execute(
            delete(Course).where(Course.year_sem == TEST_YEAR_SEM, Course.code == SEED_CODE)
        )


async def _seed(factory) -> None:
    await _wipe(factory)
    async with factory() as session, session.begin():
        session.add(
            Course(
                year_sem=TEST_YEAR_SEM,
                code=SEED_CODE,
                dept="資工系",
                grade="3",
                class_="甲班",
                name_zh="高等電腦網路",
                name_en="ADV CN",
                credit=3,
                compulsory=True,
                restrict=60,
                select_n=50,
                selected_n=40,
                remaining=10,
                teacher="林俊宏",
                room="工EC 5012",
                class_time=["", "", "234", "", "", "", ""],
                description=None,
                tags=None,
                english=False,
                change=None,
                change_desc=None,
                url="https://selcrs.nsysu.edu.tw/menu5/showoutline.asp?CrsDat=CSE515",
            )
        )


def _db_available() -> bool:
    async def probe() -> bool:
        try:
            engine, _factory = _engine_factory()
            async with engine.connect():
                pass
            await engine.dispose()
            return True
        except OSError:
            return False

    return anyio.run(probe)


pytestmark = pytest.mark.skipif(not _db_available(), reason="compose Postgres unreachable")


def _item(code: str | None, course_no: str | None) -> SelectionItem:
    return SelectionItem(
        code=code,
        course_no=course_no,
        state="選上",
        dept="資工系",
        name="高等電腦網路",
        credit=3,
        compulsory_elective="必",
        teacher="林俊宏",
        room_text="三2,3,4(工EC 5012)",
        points_priority=None,
        stage="期",
        year_semest_note="期",
        times="三2,3,4",
        room="工EC 5012",
        unknown=True,
        course_id=None,
    )


@pytest.mark.anyio
async def test_catalog_match_attaches_url_and_course_id():
    engine, factory = _engine_factory()
    try:
        await _seed(factory)
        item = _item(code="M3046243", course_no="CSE515")
        async with factory() as session, session.begin():
            joined = await attach_course_matches(session, year_sem=TEST_YEAR_SEM, items=[item])
        rows = list(joined)
        assert rows[0].unknown is False
        assert rows[0].course_id is not None
        assert rows[0].url == "https://selcrs.nsysu.edu.tw/menu5/showoutline.asp?CrsDat=CSE515"
    finally:
        if engine is not None:
            await engine.dispose()


@pytest.mark.anyio
async def test_unmatched_has_url_none():
    engine, factory = _engine_factory()
    try:
        await _seed(factory)
        item = _item(code="M9999999", course_no="CSE999")
        async with factory() as session, session.begin():
            joined = await attach_course_matches(session, year_sem=TEST_YEAR_SEM, items=[item])
        rows = list(joined)
        assert rows[0].unknown is True
        assert rows[0].course_id is None
        assert rows[0].url is None
    finally:
        if engine is not None:
            await engine.dispose()
