"""POST /api/plans/export.ics contract.

Live Compose-Postgres harness (same pattern as test_selections_join.py):
happy-path serialization against seeded catalog rows + loud 404 on unknown
ids + the empty/garbage guards that must never produce partial calendars.
"""

import uuid

import anyio
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.config import Settings
from app.db import build_engine, build_session_factory
from app.main import create_app
from app.models.courses import Course

TEST_YEAR_SEM = "1151"
SEED_CODE = "CSE515"


def _engine_factory():
    engine = build_engine(Settings())
    return engine, build_session_factory(engine)


async def _seed(factory) -> None:
    async with factory() as session, session.begin():
        await session.execute(
            delete(Course).where(Course.year_sem == TEST_YEAR_SEM, Course.code == SEED_CODE)
        )
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
                url=None,
            )
        )


async def _seed_course_id(factory) -> str:
    await _seed(factory)
    async with factory() as session:
        result = await session.execute(
            Course.__table__.select().with_only_columns(Course.id).where(
                Course.year_sem == TEST_YEAR_SEM, Course.code == SEED_CODE
            )
        )
        return str(result.scalar_one())


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


@pytest.fixture
def client():
    app = create_app(Settings(app_secret="export-ics-test-secret"))
    with TestClient(app) as test_client:
        yield test_client


def test_export_ics_happy_path_streams_deterministic_calendar(client):
    engine, factory = _engine_factory()
    try:
        course_id = anyio.run(_seed_course_id, factory)
        response = client.post(
            "/api/plans/export.ics",
            json={"plan_name": "測試課表", "course_ids": [course_id]},
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/calendar")
        assert 'filename="timetable.ics"' in response.headers["content-disposition"]
        body = response.content
        assert b"BEGIN:VCALENDAR" in body and b"END:VCALENDAR" in body
        assert body.count(b"BEGIN:VEVENT") == 1  # 234 block on one weekday = 1 event
        assert b"RRULE" in body and b"VTIMEZONE" in body
        assert "高等電腦網路".encode() in body
        assert response.content == client.post(
            "/api/plans/export.ics",
            json={"plan_name": "測試課表", "course_ids": [course_id]},
        ).content
    finally:
        anyio.run(engine.dispose)


def test_export_ics_unknown_id_answers_404_with_the_id(client):
    missing = str(uuid.uuid4())
    response = client.post("/api/plans/export.ics", json={"course_ids": [missing]})
    assert response.status_code == 404
    assert missing in response.json()["detail"]


def test_export_ics_empty_list_answers_409(client):
    response = client.post("/api/plans/export.ics", json={"course_ids": []})
    assert response.status_code == 409
    assert response.json()["detail"] == "plan_empty"


def test_export_ics_oversized_plan_answers_422(client):
    response = client.post(
        "/api/plans/export.ics",
        json={"course_ids": [str(uuid.uuid4()) for _ in range(31)]},
    )
    assert response.status_code == 422


def test_export_ics_bad_uuid_answers_422(client):
    response = client.post("/api/plans/export.ics", json={"course_ids": ["not-a-uuid"]})
    assert response.status_code == 422
