"""Postgres side of login: students upsert + write-job supersede (plan todo 8).

Runs against the REAL compose Postgres with the same skip-when-unreachable
policy as test_catalog_db.py / test_query_api.py. Seeds live under the
QA08TEST* student numbers only and are torn down at the end; real data stays
untouched. Every step gets a fresh engine per event loop (the todo-7
pattern: asyncpg pools must not cross anyio.run boundaries).
"""

import anyio
import pytest
from sqlalchemy import delete, func, select

from app.auth.students import record_successful_login
from app.config import Settings
from app.db import build_engine, build_session_factory
from app.models.students import Student
from app.models.write import WriteJob

ME = "QA08TEST01"
OTHER = "QA08TEST02"
OPS = [{"action": "+", "course_no": "CS101001"}]


def _engine_factory():
    engine = build_engine(Settings())
    return engine, build_session_factory(engine)


def _run(step):
    """Run one DB step on a fresh engine inside its own event loop."""

    async def wrapped():
        engine, factory = _engine_factory()
        try:
            return await step(factory)
        finally:
            await engine.dispose()

    return anyio.run(wrapped)


def _db_available() -> bool:
    async def probe(factory) -> bool:
        async with factory() as session:
            await session.execute(select(1))  # laziness-safe: must actually dial
        return True

    try:
        return _run(probe)
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _db_available(), reason="compose Postgres unreachable")


async def _wipe(factory) -> None:
    async with factory() as session, session.begin():
        await session.execute(
            delete(WriteJob).where(
                WriteJob.student_id.in_(
                    select(Student.id).where(Student.student_no.in_([ME, OTHER]))
                )
            )
        )
        await session.execute(delete(Student).where(Student.student_no.in_([ME, OTHER])))


async def _seed(factory) -> None:
    await _wipe(factory)
    async with factory() as session, session.begin():
        me = Student(student_no=ME)
        other = Student(student_no=OTHER)
        session.add_all([me, other])
        await session.flush()
        session.add_all(
            [
                WriteJob(student_id=me.id, status="queued", ops=OPS, payload_hash="qa08-q"),
                WriteJob(student_id=me.id, status="running", ops=OPS, payload_hash="qa08-r"),
                WriteJob(student_id=me.id, status="done", ops=OPS, payload_hash="qa08-d"),
                WriteJob(student_id=other.id, status="queued", ops=OPS, payload_hash="qa08-o"),
            ]
        )


async def _inspect(factory):
    async with factory() as session:
        students = (
            (await session.execute(select(Student).where(Student.student_no == ME)))
            .scalars()
            .all()
        )
        jobs = (
            (
                await session.execute(
                    select(WriteJob)
                    .join(Student, WriteJob.student_id == Student.id)
                    .where(Student.student_no.in_([ME, OTHER]))
                )
            )
            .scalars()
            .all()
        )
        return [(s.student_no, s.id) for s in students], [
            (j.payload_hash, j.status, j.finished_at) for j in jobs
        ]


def test_upsert_and_supersede_rule():
    # Given my queued/running/done jobs and another student's queued job
    _run(_seed)
    try:
        # When the student logs in twice in a row
        first = _run(lambda f: record_successful_login(f, ME))
        second = _run(lambda f: record_successful_login(f, ME))
        students, jobs = _run(_inspect)
        status_by_hash = {h: (s, fin) for h, s, fin in jobs}

        # Then exactly one students row exists across both logins
        assert [s_no for s_no, _id in students] == [ME]
        assert students[0][1] == first.student_id == second.student_id
        # And the first login superseded exactly queued+running (terminal and
        # foreign jobs untouched), stamping finished_at; the new login was
        # never blocked and the second login found nothing left to supersede
        assert first.superseded_jobs == 2
        assert status_by_hash["qa08-q"][0] == "session_superseded"
        assert status_by_hash["qa08-r"][0] == "session_superseded"
        assert status_by_hash["qa08-q"][1] is not None
        assert status_by_hash["qa08-d"] == ("done", None)
        assert status_by_hash["qa08-o"] == ("queued", None)
        assert second.superseded_jobs == 0
    finally:
        _run(_wipe)


def test_first_login_creates_the_student_row():
    _run(_wipe)
    try:
        # Given no row: a first successful login creates it
        _run(lambda f: record_successful_login(f, OTHER))

        async def count(factory) -> int:
            async with factory() as session:
                return (
                    await session.execute(
                        select(func.count())
                        .select_from(Student)
                        .where(Student.student_no == OTHER)
                    )
                ).scalar_one()

        assert _run(count) == 1
    finally:
        _run(_wipe)
