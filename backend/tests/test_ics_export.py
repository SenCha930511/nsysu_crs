"""ICS export tests (plan todo 12).

Part 1 - pure builder tests (no DB): RFC5545 structure via the icalendar
parser, UID/DTSTAMP determinism, CRLF + escaping roundtrip, first-occurrence
dates, loud failure on unknown period codes, degraded identity (todo 6).

Part 2 - API tests (REAL compose Postgres, same policy as test_plans_api.py):
session/ownership gates, happy-path 200 + content-type + event count, the two
friendly 409s (empty plan / unknown period), byte-identical regen.

Test identities: QA12TEST* students + year_sem=9997 courses, wiped after.
No password ever exists here (sessions seeded straight into FakeRedis).
"""

import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Final

import anyio
import pytest
from fastapi.testclient import TestClient
from icalendar import Calendar
from sqlalchemy import delete, select

from app.auth.sessions import create_site_session
from app.config import Settings
from app.db import build_engine, build_session_factory
from app.export.ics import IcsBuildError, build_plan_ics, event_uid
from app.main import create_app
from app.models.courses import Course
from app.models.students import Student

from tests.fake_redis import FakeRedis

SETTINGS: Final = Settings(
    app_secret="qa12-secret",
    semester_year_sem="9997",
    semester_start_date=date(2026, 9, 1),  # a Tuesday
    semester_end_date=date(2027, 1, 16),
)

ME = "QA12TEST01"
OTHER = "QA12TEST02"
TEST_YEAR_SEM = "9997"

COURSE_A = {
    "year_sem": TEST_YEAR_SEM,
    "code": "QA120001",
    "dept": "資訊工程學系",
    "grade": "3",
    "class_": "甲",
    "name_zh": "演算法",
    "credit": 3,
    "compulsory": False,
    "teacher": "測試教師A",
    "room": "資,101",
    "class_time": ["12", "", "34", "", "", "", ""],  # Mon 12 + Wed 34
}
COURSE_B = {
    "year_sem": TEST_YEAR_SEM,
    "code": "QA120002",
    "dept": "電機工程學系",
    "grade": "1",
    "class_": "乙",
    "name_zh": "線性代數;進階",
    "credit": 3,
    "compulsory": False,
    "teacher": "測試教師B",
    "room": "理 201",
    "class_time": ["", "", "56", "", "9", "", ""],  # Wed 56 + Fri 9
}
EXPECTED_UNTIL_UTC: Final = datetime(2027, 1, 16, 15, 59, 59, tzinfo=timezone.utc)


def _course(**overrides) -> Course:
    base = {**COURSE_A, **overrides}
    if base["class_time"] is not None:
        base["class_time"] = list(base["class_time"])
    return Course(**base)


def _events(raw: bytes) -> list:
    return list(Calendar.from_ical(raw).walk("VEVENT"))


# ---------- part 1: pure builder ----------


def test_event_count_is_sum_of_per_course_weekday_blocks() -> None:
    """Σ(per-course weekday blocks): A has 2 (Mon12, Wed34), B has 2
    (Wed56, Fri9) -> 4 VEVENTs; a Monday-only course adds exactly 1."""
    built = build_plan_ics(
        "志願A", [_course(), _course(**COURSE_B), _course(class_time=["A", "", "", "", "", "", ""])], SETTINGS
    )
    assert built.event_count == 5
    # Extra: class_time=None and all-empty days contribute zero events.
    empty = _course(class_time=["", "", "", "", "", "", ""])
    none_t = _course(class_time=None)
    built2 = build_plan_ics("X", [empty, none_t], SETTINGS)
    assert built2.event_count == 0
    assert len(_events(built2.content)) == 0


def test_rfc5545_structure_parse_assertions() -> None:
    monday_only = _course(class_time=["12", "", "", "", "", "", ""])
    built = build_plan_ics("志願A", [monday_only], SETTINGS)
    parsed = Calendar.from_ical(built.content)
    text = built.content.decode("utf-8")

    # VTIMEZONE exists, is Asia/Taipei, +08:00, no DAYLIGHT anywhere.
    vtzs = list(parsed.walk("VTIMEZONE"))
    assert len(vtzs) == 1
    assert str(vtzs[0]["TZID"]) == "Asia/Taipei"
    assert [c.name for c in vtzs[0].subcomponents] == ["STANDARD"]
    assert vtzs[0].subcomponents[0]["TZOFFSETTO"].td == timedelta(hours=8)
    assert vtzs[0].subcomponents[0]["TZOFFSETFROM"].td == timedelta(hours=8)
    assert len(list(parsed.walk("DAYLIGHT"))) == 0

    (event,) = _events(built.content)
    # DTSTART/DTEND local with TZID param; 2026-09-01 is Tuesday, so the
    # first Monday (semester start onward) is 2026-09-07; "12" -> 08:10-10:00.
    assert event["DTSTART"].params["TZID"] == "Asia/Taipei"
    assert event["DTEND"].params["TZID"] == "Asia/Taipei"
    dtstart = event.decoded("DTSTART")
    dtend = event.decoded("DTEND")
    assert dtstart == datetime(2026, 9, 7, 8, 10, tzinfo=dtstart.tzinfo)
    assert dtend == datetime(2026, 9, 7, 10, 0, tzinfo=dtend.tzinfo)

    # RRULE UNTIL is a UTC DATE-TIME (not a DATE, not a naive value).
    rrule = event.decoded("RRULE")
    (until,) = rrule["UNTIL"]
    assert isinstance(until, datetime)
    assert until.utcoffset() == timedelta(0)
    assert until == EXPECTED_UNTIL_UTC
    assert "UNTIL=20270116T155959Z" in text

    # UID deterministic shape; deterministic DTSTAMP (semester start 00:00
    # +08:00 -> 2026-08-31T16:00:00Z), never "now".
    uid = str(event["UID"])
    assert re.fullmatch(r"[0-9a-f]{40}@nsysu-course-wrapper", uid)
    dtstamp = event.decoded("DTSTAMP")
    assert dtstamp == datetime(2026, 8, 31, 16, 0, 0, tzinfo=timezone.utc)

    # SUMMARY = name（teacher）; LOCATION from room with escaping.
    assert str(event["SUMMARY"]) == "演算法（測試教師A）"
    assert str(event["LOCATION"]) == "資,101"


def test_deterministic_bytes_and_uid_dtstamp_across_regeneration() -> None:
    long_name = _course(
        name_zh="線性代數,必修;數學（二）的完整冗長課名用來觸發折疊規則驗證",
        class_time=["12", "", "", "", "", "", ""],
    )
    long_name_copy = _course(
        name_zh="線性代數,必修;數學（二）的完整冗長課名用來觸發折疊規則驗證",
        class_time=["12", "", "", "", "", "", ""],
    )
    a = build_plan_ics("志願A", [long_name], SETTINGS)
    b = build_plan_ics("志願A", [long_name_copy], SETTINGS)
    assert a.content == b.content  # UID + DTSTAMP both stable
    # And the fold-prone long CJK summary survives a parse roundtrip intact.
    (event,) = _events(a.content)
    assert str(event["SUMMARY"]).startswith("線性代數,必修;數學")
    assert "（測試教師A）" in str(event["SUMMARY"])


def test_crlf_line_endings_no_bare_lf() -> None:
    built = build_plan_ics("志願A", [_course()], SETTINGS)
    body = built.content.decode("utf-8")
    assert "\r\n" in body
    assert body.replace("\r\n", "").find("\n") == -1  # 0 bare LFs / CRs
    for line in body.split("\r\n"):
        assert len(line.encode("utf-8")) <= 75  # RFC5545 75-octet fold rule


def test_escaping_roundtrip_for_text_values() -> None:
    tricky = _course(
        name_zh=r"逗號,分號;反斜線\\換行？（不會真的有換行）",
        room="甲,101;乙202",
        teacher=None,
        class_time=["12", "", "", "", "", "", ""],
    )
    built = build_plan_ics("志願A", [tricky], SETTINGS)
    (event,) = _events(built.content)
    assert str(event["SUMMARY"]) == tricky.name_zh
    assert str(event["LOCATION"]) == "甲,101;乙202"


def test_first_occurrence_dates_per_weekday() -> None:
    """Semester starts Tue 2026-09-01: the Tuesday block starts THAT day;
    Monday/Wednesday/Sunday blocks slide to their first occurrences."""
    courses = [
        _course(class_time=["1", "2", "4", "", "", "", "7"]),  # Mon Tue Wed Sun
    ]
    built = build_plan_ics("X", courses, SETTINGS)
    starts = [e.decoded("DTSTART").date() for e in _events(built.content)]
    assert starts == [
        date(2026, 9, 7),  # Mon
        date(2026, 9, 1),  # Tue (semester start itself)
        date(2026, 9, 2),  # Wed
        date(2026, 9, 6),  # Sun
    ]
    ends = [e.decoded("DTEND") for e in _events(built.content)]
    assert ends[0].time() == time(9, 0)  # period 1 end
    assert ends[1].time() == time(10, 0)  # period 2 end


def test_unknown_period_codes_fail_loudly() -> None:
    """Unknown codes (incl. lowercase and junk chars) raise, never skip.
    (Outer whitespace is stripped first - "12 " is a clean "12", not junk.)"""
    for bad_slot in ("1Z", "Z", "a", "G", "1-2", "90"):
        course = _course(class_time=[bad_slot, "", "", "", "", "", ""])
        with pytest.raises(IcsBuildError) as got:
            build_plan_ics("X", [course], SETTINGS)
        assert got.value.slot == bad_slot
        assert bad_slot in str(got.value)
    # Sanity: the known codes still pass, and adjacent GOOD days are not
    # asked to swallow a LATER bad day.
    bad = _course(class_time=["12", "", "Q9", "", "", "", ""])
    with pytest.raises(IcsBuildError) as got2:
        build_plan_ics("X", [bad], SETTINGS)
    assert got2.value.day_index == 2


def test_uid_identity_rules() -> None:
    """School code is the UID identity (PK-independent); NULL code falls back
    to dept|name_zh|teacher|room|class_time (todo 6 degraded identity)."""
    one = _course()
    two = _course()  # identical fields, a different in-memory row
    assert event_uid(one, 1, "12") == event_uid(two, 1, "12")
    assert event_uid(one, 1, "12") != event_uid(one, 2, "34")
    assert event_uid(one, 1, "12") != event_uid(one, 1, "34")

    degraded_a = _course(code=None)
    degraded_b = _course(code=None)
    assert event_uid(degraded_a, 1, "12") == event_uid(degraded_b, 1, "12")
    # Degraded identity actually reacts to its constituents:
    changed = _course(code=None, room="別的教室")
    assert event_uid(degraded_a, 1, "12") != event_uid(changed, 1, "12")
    # ...and a code-less UID differs from the code-d version.
    assert event_uid(degraded_a, 1, "12") != event_uid(one, 1, "12")


# ---------- part 2: API (real compose Postgres) ----------


def _engine_factory():
    engine = build_engine(Settings())
    return engine, build_session_factory(engine)


def _run(step):
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
            await session.execute(select(1))
        return True

    try:
        return _run(probe)
    except OSError:
        return False


NEEDS_DB = pytest.mark.skipif(not _db_available(), reason="compose Postgres unreachable")


async def _wipe(factory) -> None:
    async with factory() as session, session.begin():
        await session.execute(delete(Course).where(Course.year_sem == TEST_YEAR_SEM))
        await session.execute(delete(Student).where(Student.student_no.in_((ME, OTHER))))


async def _fresh_seed(factory) -> tuple[uuid.UUID, uuid.UUID]:
    await _wipe(factory)
    async with factory() as session, session.begin():
        session.add_all([Student(student_no=ME), Student(student_no=OTHER)])
        a = Course(**COURSE_A)
        b = Course(**COURSE_B)
        session.add_all([a, b])
        await session.flush()
        return a.id, b.id


@dataclass
class Harness:
    client: TestClient
    course_a: uuid.UUID
    course_b: uuid.UUID

    @property
    def redis(self) -> FakeRedis:
        return self.client.app.state.redis

    def auth(self, student_no: str = ME) -> dict[str, str]:
        session_id = anyio.run(create_site_session, self.redis, student_no)
        return {"session_id": session_id}

    def create_plan(self, name: str, student_no: str = ME) -> dict:
        response = self.client.post(
            "/api/plans", json={"name": name}, cookies=self.auth(student_no)
        )
        assert response.status_code == 201, response.text
        return response.json()

    def add_items(self, plan_id: str, course_ids: list[str]) -> None:
        response = self.client.put(
            f"/api/plans/{plan_id}/items",
            json={"items": [{"course_id": cid} for cid in course_ids]},
            cookies=self.auth(),
        )
        assert response.status_code == 200, response.text


@pytest.fixture
def harness():
    app = create_app(Settings())
    with TestClient(app) as test_client:
        test_client.app.state.redis = FakeRedis()
        a, b = _run(_fresh_seed)
        yield Harness(client=test_client, course_a=a, course_b=b)
        _run(_wipe)


@NEEDS_DB
def test_export_happy_path_status_headers_and_event_math(harness) -> None:
    plan = harness.create_plan("匯出測試")
    harness.add_items(plan["id"], [str(harness.course_a), str(harness.course_b)])
    parsed_uids: set[str] = set()
    for _ in range(2):  # two generations: byte-identical (UID/DTSTAMP stable)
        response = harness.client.get(
            f"/api/plans/{plan['id']}/export.ics", cookies=harness.auth()
        )
        assert response.status_code == 200, response.text
        ctype = response.headers["content-type"]
        assert ctype.startswith("text/calendar") and "charset=utf-8" in ctype
        disposition = response.headers["content-disposition"]
        assert disposition.startswith("attachment")
        assert "filename*=UTF-8''nsysu-crs-" in quote_insensitive(disposition)
        body = response.content  # bytes: CRLF intact through ASGI
        assert body.startswith(b"BEGIN:VCALENDAR\r\n")
        events = _events(body)
        assert len(events) == 4  # A: Mon12+Wed34; B: Wed56+Fri90
        rrules = [e.decoded("RRULE") for e in events]
        for (until,) in (rr["UNTIL"] for rr in rrules):
            assert isinstance(until, datetime) and until.utcoffset() == timedelta(0)
        assert len(list(Calendar.from_ical(body).walk("VTIMEZONE"))) == 1
        if parsed_uids:
            assert {str(e["UID"]) for e in events} == parsed_uids
        parsed_uids = {str(e["UID"]) for e in events}


def quote_insensitive(value: str) -> str:
    """Content-Disposition may be sent through Caddy casing-preserved; compare
    as-is (FastAPI emits exactly what we set)."""
    return value


@NEEDS_DB
def test_export_requires_session_and_ownership(harness) -> None:
    mine = harness.create_plan("我的")
    pid = mine["id"]
    assert harness.client.get(f"/api/plans/{pid}/export.ics").status_code == 401
    foreign = harness.client.get(f"/api/plans/{pid}/export.ics", cookies=harness.auth(OTHER))
    assert foreign.status_code == 404
    assert foreign.json()["detail"] == "plan_not_found"
    missing = harness.client.get(
        f"/api/plans/{uuid.uuid4()}/export.ics", cookies=harness.auth()
    )
    assert missing.status_code == 404


@NEEDS_DB
def test_export_empty_plan_is_friendly_409_not_a_file(harness) -> None:
    """Empty plan (and unknown-uuid-only plan): 409 + friendly JSON, no file."""
    empty = harness.create_plan("空課表")
    response = harness.client.get(
        f"/api/plans/{empty['id']}/export.ics", cookies=harness.auth()
    )
    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/json")
    detail = response.json()["detail"]
    assert detail["code"] == "plan_empty_no_events"
    assert "課表" in detail["message"]

    placeholders = harness.create_plan("只有未知課")
    harness.add_items(placeholders["id"], [str(uuid.uuid4()), "not-a-uuid"])
    response2 = harness.client.get(
        f"/api/plans/{placeholders['id']}/export.ics", cookies=harness.auth()
    )
    assert response2.status_code == 409
    assert response2.json()["detail"]["code"] == "plan_empty_no_events"


@NEEDS_DB
def test_export_unknown_period_code_is_friendly_409(harness) -> None:
    bad_id = _run(_add_bad_course)
    plan = harness.create_plan("壞時間課表")
    harness.add_items(plan["id"], [str(bad_id)])
    response = harness.client.get(
        f"/api/plans/{plan['id']}/export.ics", cookies=harness.auth()
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "bad_period_code"
    assert "課程" in detail["message"] and "Z" in detail["message"]
    assert detail["day_index"] == 0


async def _add_bad_course(factory) -> uuid.UUID:
    async with factory() as session, session.begin():
        bad = Course(
            **{**COURSE_A, "code": "QA12BAD1", "name_zh": "壞時間課", "class_time": ["1Z", "", "", "", "", "", ""]}
        )
        session.add(bad)
        await session.flush()
        return bad.id
