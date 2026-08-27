"""DB-backed resolve_course tests (plan todo 14 check 3).

Needs a reachable Postgres (compose service), else SKIPs like the catalog
DB tests - the API-level checks are stub-covered offline; here only the real
SQL semantics are pinned: uuid-vs-code dispatch, the current-semester
filter, CHAR(8) code handling, and NULL-code rows. Non-destructive: its own
semester namespace, deleted again at teardown.
"""

from datetime import UTC, datetime

import anyio
import pytest
from sqlalchemy import delete

from app.config import Settings
from app.db import build_engine, build_session_factory
from app.models.courses import Course
from app.write.catalog import COURSE_NOT_FOUND, resolve_course, resolve_courses_by_ids

TEST_YEAR_SEM = "QA14RES"


def _taiwan_session_factory():
    settings = Settings()
    engine = build_engine(settings)
    return engine, build_session_factory(engine)


def _db_available() -> bool:
    async def probe() -> bool:
        try:
            engine, _ = _taiwan_session_factory()
            async with engine.connect():
                pass
            await engine.dispose()
            return True
        except OSError:
            return False

    return anyio.run(probe)


pytestmark = pytest.mark.skipif(not _db_available(), reason="compose Postgres unreachable")


def _course(code: str | None) -> Course:
    return Course(
        year_sem=TEST_YEAR_SEM,
        code=code,
        name_zh="QA14 測試課",
        credit=3,
        compulsory=False,
        class_time=["", "", "234", "", "", "", ""],
        restrict=60,
        select_n=50,
        selected_n=40,
        remaining=20,
        ingested_at=datetime(2026, 8, 28, 3, 10, tzinfo=UTC),
    )


@pytest.fixture
async def seeded():
    engine, session_factory = _taiwan_session_factory()
    async with session_factory() as session, session.begin():
        coded, codeless = _course("QA000001"), _course(None)
        session.add_all([coded, codeless])
        await session.flush()
        ids = {"coded": str(coded.id), "codeless": str(codeless.id)}
    try:
        yield session_factory, ids
    finally:
        async with session_factory() as session, session.begin():
            await session.execute(delete(Course).where(Course.year_sem == TEST_YEAR_SEM))
        await engine.dispose()


@pytest.mark.anyio
async def test_resolve_by_school_code_and_by_uuid(seeded):
    session_factory, ids = seeded
    async with session_factory() as db:
        by_code = await resolve_course(db, year_sem=TEST_YEAR_SEM, ident="QA000001")
        by_uuid = await resolve_course(db, year_sem=TEST_YEAR_SEM, ident=ids["coded"])
    assert by_code.code == "QA000001" and by_code.course_id == ids["coded"]
    assert by_code.class_time == ("", "", "234", "", "", "", "")
    assert by_code.remaining == 20
    assert by_uuid == by_code


@pytest.mark.anyio
async def test_wrong_semester_and_unknown_ident_resolve_as_not_found(seeded):
    session_factory, ids = seeded
    async with session_factory() as db:
        foreign = await resolve_course(db, year_sem="1151", ident=ids["coded"])
        unknown = await resolve_course(db, year_sem=TEST_YEAR_SEM, ident="NOSUCH01")
    assert foreign is COURSE_NOT_FOUND
    assert unknown is COURSE_NOT_FOUND


@pytest.mark.anyio
async def test_null_code_row_resolves_with_code_none(seeded):
    session_factory, ids = seeded
    async with session_factory() as db:
        info = await resolve_course(db, year_sem=TEST_YEAR_SEM, ident=ids["codeless"])
    assert info.course_id == ids["codeless"]  # row exists....
    assert info.code is None  # ...but stays 無課號-non-submittable


@pytest.mark.anyio
async def test_resolve_courses_by_ids_filters_garbage_and_semester(seeded):
    session_factory, ids = seeded
    async with session_factory() as db:
        matched = await resolve_courses_by_ids(
            db,
            year_sem=TEST_YEAR_SEM,
            course_ids=[ids["coded"], "not-a-uuid", ids["codeless"]],
        )
        empty = await resolve_courses_by_ids(db, year_sem=TEST_YEAR_SEM, course_ids=[])
    assert set(matched) == {ids["coded"], ids["codeless"]}
    assert matched[ids["coded"]].code == "QA000001"
    assert empty == {}
