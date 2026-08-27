"""Query API + catalog meta tests (plan todo 7, QA qa/07-query.log).

DB-backed cases run against the REAL compose Postgres (same skip-when-
unreachable policy as test_catalog_db.py): seeds live in year_sem=9999 only
and are deleted at teardown, so the real 1151 snapshot stays intact. Parser /
serializer logic is covered by pure unit tests (no DB needed).
"""

from datetime import UTC, datetime

import anyio
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app.api.catalog import meta_payload
from app.api.deps import get_session
from app.catalog.meta import CatalogMeta, latest_catalog_meta
from app.catalog.query import (
    PER_PAGE,
    CourseQueryError,
    parse_course_params,
    resolve_year_sem,
)
from app.config import Settings
from app.db import build_engine, build_session_factory
from app.main import create_app
from app.models.courses import Course, IngestRun

TEST_YEAR_SEM = "9999"
EMPTY = ("", "", "", "", "", "", "")

# (code, dept, grade, name_zh, name_en, credit, compulsory, english, teacher, slots Mon..Sun)
SEED = [
    ("CS101000", "資訊工程學系", "1", "程式設計(一)", "Programming I", 3, True, False, "陳志強", ("12", "", "", "", "", "", "")),
    ("CS102000", "資訊工程學系", "2", "資料結構", "Data Structures", 3, True, False, "黃雅婷", ("", "", "56", "", "", "", "")),
    ("CS201000", "資訊工程學系", "3", "作業系統", "Operating Systems", 3, False, False, "陳志強", ("AB", "", "", "", "", "", "")),
    ("EE101000", "電機工程學系", "1", "電路學", "Circuit Theory", 3, True, False, "林俊宏", ("", "34", "", "", "", "", "")),
    ("EE205000", "電機工程學系", "2", "電磁學", "Electromagnetics", 0, True, False, "王大明", ("", "", "", "", "7", "", "")),
    ("MA101000", "應用數學系", "1", "微積分(一)", "Calculus I", 3, True, False, "張美玲", ("", "", "", "9C", "", "", "")),
    ("MA203000", "應用數學系", "3", "機率論", "Probability", 3, False, False, "張美玲", ("", "", "", "", "", "D", "")),
    ("GE100000", "通識教育中心", "0", "海洋與社會", "Ocean and Society", 2, False, False, "林育成", ("", "", "", "", "", "", "F")),
    (None, "通識教育中心", "0", "服務學習", "Service Learning", 1, False, False, "李社工", EMPTY),
    ("IB501000", "國際學程", "1", "國際企業管理", "International Business Management", 3, False, True, "John Smith", ("56", "", "", "", "", "", "")),
    ("FL102000", "外國語文學系", "1", "英文作文", "English Composition", 2, False, True, "Mary Johnson", ("", "", "", "", "", "8", "")),
    ("PE101000", "體育教育中心", "1", "游泳", "Swimming", 0, False, False, "吳健", ("", "", "", "E", "", "", "")),
]


def _course(row) -> Course:
    code, dept, grade, name_zh, name_en, credit, comp, eng, teacher, slots = row
    return Course(
        year_sem=TEST_YEAR_SEM, code=code, dept=dept, grade=grade, class_="甲",
        name_zh=name_zh, name_en=name_en, credit=credit, compulsory=comp,
        english=eng, teacher=teacher, room="測101", class_time=list(slots),
    )


async def _wipe_seeds(factory) -> None:
    async with factory() as session, session.begin():
        await session.execute(delete(Course).where(Course.year_sem == TEST_YEAR_SEM))


def _engine_factory():
    engine = build_engine(Settings())
    return engine, build_session_factory(engine)


async def _seed(factory) -> None:
    await _wipe_seeds(factory)
    async with factory() as session, session.begin():
        session.add_all(_course(row) for row in SEED)


def _db_available() -> bool:
    async def probe() -> bool:
        try:
            engine, factory = _engine_factory()
            async with engine.connect():
                pass
            await engine.dispose()
            return True
        except OSError:
            return False

    return anyio.run(probe)


pytestmark = pytest.mark.skipif(not _db_available(), reason="compose Postgres unreachable")


@pytest.fixture(scope="module")
def client():
    async def seed_run():
        engine, factory = _engine_factory()
        try:
            await _seed(factory)
        finally:
            await engine.dispose()

    async def cleanup_run():
        engine, factory = _engine_factory()
        try:
            await _wipe_seeds(factory)
        finally:
            await engine.dispose()

    anyio.run(seed_run)
    app = create_app(Settings())
    with TestClient(app) as test_client:
        yield test_client
    anyio.run(cleanup_run)


def _names(body) -> set[str]:
    return {item["name_zh"] for item in body["items"]}


def _get(client, **params) -> dict:
    response = client.get("/api/courses", params=params)
    assert response.status_code == 200, response.text
    return response.json()


# ---------- /api/courses: paging + single filters (seeded 12 courses) ----------

def test_total_and_paging_math(client):
    body = _get(client, year_sem=TEST_YEAR_SEM)
    assert (body["page"], body["per_page"], body["total"]) == (1, PER_PAGE, 12)
    assert len(body["items"]) == 12
    for item in body["items"]:
        assert item["year_sem"] == TEST_YEAR_SEM
        assert item["class_time"] is None or len(item["class_time"]) == 7
    page2 = _get(client, year_sem=TEST_YEAR_SEM, page=2)
    assert (page2["page"], page2["total"], page2["items"]) == (2, 12, [])


def test_default_year_sem_is_freshest_in_catalog(client):
    body = client.get("/api/courses").json()
    assert body["total"] == 12 and {i["year_sem"] for i in body["items"]} == {TEST_YEAR_SEM}


def test_q_matches_name_and_teacher(client):
    assert _names(_get(client, year_sem=TEST_YEAR_SEM, q="資料")) == {"資料結構"}
    teacher = _get(client, year_sem=TEST_YEAR_SEM, q="張美玲")
    assert _names(teacher) == {"微積分(一)", "機率論"}
    assert all(item["teacher"] == "張美玲" for item in teacher["items"])
    assert _names(_get(client, year_sem=TEST_YEAR_SEM, q="international")) == {"國際企業管理"}


def test_single_dimension_filters(client):
    dept = _get(client, year_sem=TEST_YEAR_SEM, dept="資訊工程學系")
    assert dept["total"] == 3 and all(i["dept"] == "資訊工程學系" for i in dept["items"])
    grade = _get(client, year_sem=TEST_YEAR_SEM, grade="1")
    assert grade["total"] == 6 and all(i["grade"] == "1" for i in grade["items"])
    for credit, expected in ((0, 2), (3, 7)):
        body = _get(client, year_sem=TEST_YEAR_SEM, credit=credit)
        assert body["total"] == expected and all(i["credit"] == credit for i in body["items"])
    for flag, expected in (("true", 5), ("false", 7)):
        body = _get(client, year_sem=TEST_YEAR_SEM, compulsory=flag)
        want = flag == "true"
        assert body["total"] == expected and all(i["compulsory"] is want for i in body["items"])
    for flag, expected in (("true", 2), ("false", 10)):
        body = _get(client, year_sem=TEST_YEAR_SEM, english=flag)
        want = flag == "true"
        assert body["total"] == expected and all(i["english"] is want for i in body["items"])
    assert _names(_get(client, year_sem=TEST_YEAR_SEM, weekday=1)) == {
        "程式設計(一)", "作業系統", "國際企業管理"}
    assert _names(_get(client, year_sem=TEST_YEAR_SEM, weekday=5)) == {"電磁學"}


def test_weekday_period_combo(client):
    body = _get(client, year_sem=TEST_YEAR_SEM, weekday=3, period=5)
    assert _names(body) == {"資料結構"}  # Wed-56 hit; Mon-'AB' 作業系統 excluded
    assert _names(_get(client, year_sem=TEST_YEAR_SEM, weekday=1, period="A")) == {"作業系統"}


def test_null_code_row_serializes(client):
    body = _get(client, year_sem=TEST_YEAR_SEM, q="服務學習")
    assert body["total"] == 1
    assert body["items"][0]["code"] is None
    assert body["items"][0]["class_time"] == list(EMPTY)


# ---------- /api/courses: illegal params -> 400 with a clear message ----------

@pytest.mark.parametrize(
    "params,needle",
    [
        ({"period": "Z"}, "period"),
        ({"period": "56"}, "period"),
        ({"grade": "9"}, "grade"),
        ({"weekday": "8"}, "weekday"),
        ({"weekday": "0"}, "weekday"),
        ({"page": "0"}, "page"),
        ({"credit": "abc"}, "credit"),
        ({"compulsory": "maybe"}, "compulsory"),
        ({"bogus": "1"}, "unknown query parameter"),
        ({"year_sem": "abcd"}, "year_sem"),
    ],
)
def test_illegal_params_400(client, params, needle):
    response = client.get("/api/courses", params=params)
    assert response.status_code == 400
    assert needle in response.json()["detail"]


def test_period_without_weekday_400(client):
    response = client.get("/api/courses", params={"period": "5"})
    assert response.status_code == 400 and "weekday" in response.json()["detail"]


# ---------- /api/catalog/meta ----------

def test_meta_endpoint_reflects_latest_ingest_run(client):
    async def ground_truth():
        engine, factory = _engine_factory()
        try:
            async with factory() as session:
                meta = await latest_catalog_meta(session)
                assert meta is not None
                return meta
        finally:
            await engine.dispose()

    expected = anyio.run(ground_truth)
    response = client.get("/api/catalog/meta")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] == expected.ok
    assert body["row_count"] == expected.row_count
    assert body["source"] == "self-scrape"
    assert datetime.fromisoformat(body["updated_at"]) == expected.updated_at


class _StubSession:
    """Minimal AsyncSession quacker: latest_catalog_meta sees a scripted run."""

    def __init__(self, run: IngestRun) -> None:
        self._run = run

    async def execute(self, _stmt):
        class _Result:
            def __init__(self, value) -> None:
                self._value = value

            def scalar_one_or_none(self):
                return self._value

        return _Result(self._run)


def test_meta_failed_run_still_answers_200_with_ok_false():
    stamp = datetime(2026, 8, 28, 2, 13, 10, tzinfo=UTC)
    run = IngestRun(ok=False, started_at=stamp, finished_at=stamp,
                    rows=None, source="self-scrape", error="scripted outage")
    app = create_app(Settings())
    app.dependency_overrides[get_session] = lambda: _StubSession(run)
    with TestClient(app) as client:
        response = client.get("/api/catalog/meta")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False and body["row_count"] is None
    assert body["source"] == "self-scrape"
    assert datetime.fromisoformat(body["updated_at"]) == stamp


# ---------- pure parser / mapper unit tests (no DB needed) ----------

def test_parse_defaults_and_period_casefold():
    filt = parse_course_params({}, default_year_sem="1151")
    assert filt == parse_course_params({"year_sem": "1151"}, default_year_sem="9999")
    assert filt.page == 1 and filt.period is None and filt.weekday is None
    upper = parse_course_params({"weekday": "3", "period": "a"}, default_year_sem="1151")
    assert (upper.weekday, upper.period, upper.year_sem) == (3, "A", "1151")


@pytest.mark.parametrize(
    "params",
    [{"period": "Z"}, {"period": "56"}, {"grade": "9"}, {"weekday": "8"},
     {"weekday": "0"}, {"page": "0"}, {"page": "-1"}, {"credit": "-1"},
     {"credit": "abc"}, {"compulsory": "maybe"}, {"english": "2"},
     {"bogus": "1"}, {"year_sem": "115"}, {"period": "5"}],
)
def test_parse_rejects_illegal_values(params):
    with pytest.raises(CourseQueryError):
        parse_course_params(params, default_year_sem="1151")


def test_resolve_year_sem_and_meta_payload():
    assert resolve_year_sem(None, "1151") == "1151"
    assert resolve_year_sem("9999", "1151") == "9999"

    empty = meta_payload(None)
    assert (empty.ok, empty.updated_at, empty.row_count, empty.source) == (
        False, None, None, "self-scrape")

    stamp = datetime(2026, 8, 28, 2, 13, 10, tzinfo=UTC)
    good = meta_payload(CatalogMeta(ok=True, updated_at=stamp, row_count=2596,
                                    source="self-scrape"))
    assert (good.ok, good.row_count, good.updated_at) == (True, 2596, stamp)
    failed = meta_payload(CatalogMeta(ok=False, updated_at=stamp, row_count=None,
                                      source="self-scrape"))
    assert (failed.ok, failed.row_count, failed.updated_at) == (False, None, stamp)


def test_total_count_uses_same_filters_as_slice(client):
    async def count_directly() -> int:
        engine, factory = _engine_factory()
        try:
            async with factory() as session:
                return (await session.execute(
                    select(func.count()).select_from(Course).where(
                        Course.year_sem == TEST_YEAR_SEM)
                )).scalar_one()
        finally:
            await engine.dispose()

    assert _get(client, year_sem=TEST_YEAR_SEM)["total"] == anyio.run(count_directly)
