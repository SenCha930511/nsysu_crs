"""POST /api/write/submit contract tests (plan todo 15; QA qa/15-*.log).

DB-backed against the REAL compose Postgres (skip-when-unreachable + fresh
engine per DB step, the test_auth_db.py pattern); Redis is FakeRedis; the
school is scripted at the adapter seams (SSO2 re-auth at app.api.auth +
app.api.write_submit, the preview probe at app.api.write_probe, catalog at
app.api.write). Students login through the REAL endpoint, so the shipped
students/jar/session paths are the tested ones.
"""

import uuid
from dataclasses import dataclass, field
from pathlib import Path

import anyio
import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.config import Settings
from app.db import build_engine, build_session_factory
from app.main import create_app
from app.models.students import Student
from app.models.write import WriteAudit, WriteJob
from app.selcrs.endpoints import Sso2Result
from app.selcrs.sso2 import Sso2Outcome
from app.selections.parse import SelectionItem
from app.selections.store import SelectionsSnapshot, store_snapshot
from app.write.canonical import CanonicalOp, canonical_segments, payload_hash
from app.write.catalog import COURSE_NOT_FOUND, CourseInfo
from app.write.queue import TICKET_FIELDS, parse_ticket
from tests.fake_redis import FakeRedis

FIXTURES = Path(__file__).parent / "fixtures"
STUDENT = "QA15TEST01"
OTHER = "QA15TEST02"
PASSWORD = "qa15-submit-password"
CSRF = "qa15-csrf-token"
FORM_URL = (
    "https://selcrs.nsysu.edu.tw/menu4/addcourse/ssform.asp"
    "?X1=09&X2=0&DEG_COD=B&college=1&dept=36&grade=1&SCH_COD=2&USE_YR=115&EDU=B"
)
OPS_SEGMENTS = "-:M3046243:|+:GEAE2526:01|+:MEME101B:02"


def _load(name: str, encoding: str = "utf-8") -> str:
    return (FIXTURES / name).read_bytes().decode(encoding)


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


async def _arun(step):
    """Async twin of _run (usable inside an already-running test loop)."""
    engine, factory = _engine_factory()
    try:
        return await step(factory)
    finally:
        await engine.dispose()


def _db_available() -> bool:
    async def probe(factory) -> bool:
        async with factory() as session:
            await session.execute(select(1))
        return True

    try:
        return _run(probe)
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _db_available(), reason="compose Postgres unreachable")


async def _wipe(factory) -> None:
    async with factory() as session, session.begin():
        ids = select(Student.id).where(Student.student_no.in_([STUDENT, OTHER]))
        job_ids = select(WriteJob.id).where(WriteJob.student_id.in_(ids))
        await session.execute(delete(WriteAudit).where(WriteAudit.job_id.in_(job_ids)))
        await session.execute(delete(WriteJob).where(WriteJob.student_id.in_(ids)))
        await session.execute(delete(Student).where(Student.student_no.in_([STUDENT, OTHER])))


async def _jobs_for_students(factory) -> list[WriteJob]:
    async with factory() as session:
        return list(
            (
                await session.execute(
                    select(WriteJob)
                    .join(Student, WriteJob.student_id == Student.id)
                    .where(Student.student_no.in_([STUDENT, OTHER]))
                )
            )
            .scalars()
            .all()
        )


def _selection_item(code: str) -> SelectionItem:
    return SelectionItem(
        code=code,
        course_no="GE2526",
        state="選上",
        dept="通識",
        name="某通識課",
        credit=2,
        compulsory_elective="選",
        teacher="某人",
        room_text="",
        points_priority=None,
        stage="0",
        year_semest_note="期",
        times=None,
        room=None,
        unknown=True,
        course_id=None,
    )


@dataclass
class StubSso2:
    """Scripted SSO2: SUCCESS with per-call distinct cookie values, or fail."""

    fail: bool = False
    calls: list[tuple[str, str]] = field(default_factory=list)

    async def login_sso2(self, student_no: str, password: str, transport=None) -> Sso2Result:
        self.calls.append((student_no, password))
        if self.fail:
            return Sso2Result(
                outcome=Sso2Outcome.CREDENTIAL_FAIL,
                cookies=httpx.Cookies(),
                detail="學號碼密碼不符",
            )
        jar = httpx.Cookies()
        jar.set("ASPSESSIONIDQATEST", f"QA15-COOKIE-{len(self.calls):03d}")
        return Sso2Result(outcome=Sso2Outcome.SUCCESS, cookies=jar, detail=None)


@dataclass
class StubProbe:
    studfun_calls: int = 0
    form_calls: int = 0

    async def get_studfun(self) -> str:
        self.studfun_calls += 1
        return _load("studfun_open_ssform_provisional.html")

    async def get_write_form(self, form_url: str) -> str:
        self.form_calls += 1
        assert form_url == FORM_URL
        return _load("ssform_provisional.html", "big5hkscs")


@dataclass
class Harness:
    client: TestClient
    redis: FakeRedis
    sso2: StubSso2
    probe: StubProbe
    catalog: dict
    csrf: str = CSRF

    def login(self, student: str = STUDENT) -> str:
        response = self.client.post(
            "/api/auth/login", json={"student_no": student, "password": PASSWORD}
        )
        assert response.status_code == 200, response.text
        self.csrf = response.json()["csrf_token"]
        return self.csrf

    async def seed_selections(self, codes: list[str]) -> None:
        session_id = self.client.cookies.get("session_id")
        assert session_id
        await store_snapshot(
            self.redis,
            session_id,
            SelectionsSnapshot(
                synced_at="2026-08-28T09:00:00+08:00",
                items=[_selection_item(code) for code in codes],
            ),
        )

    def preview(self, ops: list[dict], csrf: str) -> dict:
        response = self.client.post(
            "/api/write/preview", json={"ops": ops}, headers={"X-CSRF-Token": csrf}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["writable"] is True, body
        assert body["canonical_ops"] == OPS_SEGMENTS
        return body

    def submit(self, token: str, password: str = PASSWORD, csrf: str | None = None):
        return self.client.post(
            "/api/write/submit",
            json={"confirm_token": token, "password": password},
            headers={"X-CSRF-Token": csrf or self.csrf},
        )


def _make_harness(monkeypatch) -> Harness:
    app = create_app(Settings(app_secret="qa15-test-secret"))
    client = TestClient(app, base_url="https://testserver")
    sso2 = StubSso2()
    probe = StubProbe()
    catalog = {
        code: CourseInfo(
            course_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"qa15.{code}")),
            code=code,
            class_time=(),
            restrict=60,
            select_n=50,
            selected_n=40,
            remaining=10,
            ingested_at="2026-08-28T03:10:00+08:00",
        )
        for code in ("GEAE2526", "MEME101B", "M3046243")
    }
    harness = Harness(client=client, redis=FakeRedis(), sso2=sso2, probe=probe, catalog=catalog)

    async def stub_resolve(db, *, year_sem, ident):
        return harness.catalog.get(ident, COURSE_NOT_FOUND)

    async def stub_resolve_ids(db, *, year_sem, course_ids):
        return {}

    monkeypatch.setattr("app.api.auth.login_sso2", sso2.login_sso2)
    monkeypatch.setattr("app.api.write_submit.login_sso2", sso2.login_sso2)
    monkeypatch.setattr("app.api.write_probe.get_studfun", probe.get_studfun)
    monkeypatch.setattr("app.api.write_probe.get_write_form", probe.get_write_form)
    monkeypatch.setattr("app.api.write.resolve_course", stub_resolve)
    monkeypatch.setattr("app.api.write.resolve_courses_by_ids", stub_resolve_ids)
    client.__enter__()
    client.app.state.redis = harness.redis
    return harness


@pytest.fixture
def harness_factory(monkeypatch):
    built: list[Harness] = []

    def factory() -> Harness:
        harness = _make_harness(monkeypatch)
        built.append(harness)
        return harness

    yield factory
    for harness in built:
        harness.client.__exit__(None, None, None)


@pytest.fixture
def harness(harness_factory):
    _run(_wipe)
    built = harness_factory()
    yield built
    _run(_wipe)


def _batch() -> list[dict]:
    return [
        {"action": "+", "course_id": "GEAE2526", "priority": 1},
        {"action": "+", "course_id": "MEME101B", "priority": 2},
        {"action": "-", "course_id": "M3046243", "drop_confirm_text": "M3046243"},
    ]


async def _prepare(harness: Harness) -> tuple[str, dict]:
    """Login + selections seed + preview; returns (csrf, preview body)."""
    csrf = harness.login()
    await harness.seed_selections(["M3046243"])
    return csrf, harness.preview(_batch(), csrf)


# ---------- happy path (QA qa/15-submit.log) ----------


@pytest.mark.anyio
async def test_submit_enqueues_with_fresh_jar_and_clean_ticket(harness):
    csrf, body = await _prepare(harness)
    calls_before = list(harness.sso2.calls)

    response = harness.submit(body["confirm_token"], csrf=csrf)

    assert response.status_code == 202, response.text
    content = response.json()
    assert content["status"] == "queued"
    assert content["payload_hash"] == body["payload_hash"]
    # The password was re-verified RIGHT NOW with the submitted value.
    assert harness.sso2.calls[len(calls_before) :] == [(STUDENT, PASSWORD)]
    # The fresh jar overwrote the session's selcrs entry (never Postgres).
    session_id = harness.client.cookies.get("session_id")
    jar_payload = harness.redis.peek(f"selcrs:{session_id}")
    assert jar_payload is not None
    assert "QA15-COOKIE-002" in jar_payload  # login's jar was ...-001
    # DB ledger: exactly one queued job with canonical ops.
    jobs = await _arun(_jobs_for_students)
    assert len(jobs) == 1
    assert jobs[0].status == "queued"
    assert jobs[0].ops == [
        {"action": "-", "code": "M3046243", "priority": None},
        {"action": "+", "code": "GEAE2526", "priority": 1},
        {"action": "+", "code": "MEME101B", "priority": 2},
    ]
    expected_hash = payload_hash(
        STUDENT,
        [
            CanonicalOp(action="-", code="M3046243"),
            CanonicalOp(action="+", code="GEAE2526", priority=1),
            CanonicalOp(action="+", code="MEME101B", priority=2),
        ],
    )
    assert content["payload_hash"] == expected_hash
    # FIFO ticket: the whitelist, session_ref bound, no secret shape.
    tickets = harness.redis.lmembers("writeq:jobs")
    assert len(tickets) == 1
    ticket = parse_ticket(tickets[0])
    assert ticket is not None
    assert set(ticket.model_dump()) == TICKET_FIELDS
    assert ticket.job_id == content["job_id"]
    assert ticket.session_ref == session_id
    assert ticket.student_no == STUDENT
    assert ticket.canonical_ops == OPS_SEGMENTS
    assert ticket.variant == "ssform" and ticket.form_url == FORM_URL
    folded = tickets[0].lower()
    for denied in ("password", "cookie", "secret", "csrf", "spassword"):
        assert denied not in folded


# ---------- confirm-token boundary ----------


@pytest.mark.anyio
async def test_unknown_token_is_409_without_any_school_call(harness):
    harness.login()
    before = list(harness.sso2.calls)
    response = harness.submit("never-minted")
    assert (response.status_code, response.json()["detail"]) == (409, "confirm_token_unknown")
    assert harness.sso2.calls == before  # GETDEL precedes the re-auth


@pytest.mark.anyio
async def test_replayed_token_is_409_and_school_sees_exactly_one_job(harness):
    csrf, body = await _prepare(harness)
    assert harness.submit(body["confirm_token"], csrf=csrf).status_code == 202
    response = harness.submit(body["confirm_token"], csrf=csrf)
    assert (response.status_code, response.json()["detail"]) == (409, "confirm_token_unknown")
    assert len(await _arun(_jobs_for_students)) == 1  # double-click minted one job


@pytest.mark.anyio
async def test_repreview_then_submit_is_409_carrying_the_existing_job_id(harness):
    csrf, first = await _prepare(harness)
    created = harness.submit(first["confirm_token"], csrf=csrf).json()
    second = harness.preview(_batch(), csrf)  # same batch re-mints the same token
    assert second["confirm_token"] == first["confirm_token"]
    response = harness.submit(second["confirm_token"], csrf=csrf)
    assert (response.status_code, response.json()["detail"]) == (409, "duplicate_active_job")
    assert response.json()["job_id"] == created["job_id"]
    assert len(await _arun(_jobs_for_students)) == 1


@pytest.mark.anyio
async def test_a_token_minted_by_another_student_is_409(harness):
    csrf_a = harness.login(STUDENT)
    await harness.seed_selections(["M3046243"])
    token = harness.preview(_batch(), csrf_a)["confirm_token"]
    harness.client.post("/api/auth/logout")
    csrf_b = harness.login(OTHER)
    response = harness.submit(token, csrf=csrf_b)
    assert (response.status_code, response.json()["detail"]) == (409, "confirm_token_unknown")
    assert await _arun(_jobs_for_students) == []


# ---------- re-auth boundary ----------


@pytest.mark.anyio
async def test_wrong_password_is_401_and_nothing_is_enqueued(harness):
    csrf, body = await _prepare(harness)
    harness.sso2.fail = True  # NOW the submit-side re-auth must fail
    response = harness.submit(body["confirm_token"], password="wrong", csrf=csrf)
    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_credentials"
    assert await _arun(_jobs_for_students) == []  # never enqueued
    assert harness.redis.keys_with_prefix("writeq:") == []
    assert harness.redis.lmembers("writeq:jobs") == []


@pytest.mark.anyio
async def test_submit_without_a_token_is_400(harness):
    harness.login()
    response = harness.client.post(
        "/api/write/submit",
        json={"password": PASSWORD},
        headers={"X-CSRF-Token": harness.csrf},
    )
    assert (response.status_code, response.json()["detail"]) == (400, "confirm_token_required")


def test_submit_requires_csrf(harness):
    harness.login()
    response = harness.client.post(
        "/api/write/submit", json={"confirm_token": "x", "password": PASSWORD}
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "csrf_failed"}


def test_canonical_segments_constant_matches_output():
    assert canonical_segments(
        [
            CanonicalOp(action="-", code="M3046243"),
            CanonicalOp(action="+", code="GEAE2526", priority=1),
            CanonicalOp(action="+", code="MEME101B", priority=2),
        ]
    ) == OPS_SEGMENTS
