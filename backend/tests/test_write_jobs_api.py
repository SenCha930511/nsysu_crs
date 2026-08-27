"""GET /api/write/jobs/{job_id} tests (plan todo 15 deliverable 5).

Owner-only reads, distinct terminal messages, and outcome surfacing from
the audit ledger. Same infra as test_write_submit_api.py (REAL compose
Postgres + FakeRedis + scripted school; students through the real login).
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
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
from app.write.catalog import COURSE_NOT_FOUND
from app.write.jobs import audit_stuid_hash
from app.write.outcomes import OUTCOME_STAGE_EXPIRED, OUTCOME_UNKNOWN_RECONCILED
from tests.fake_redis import FakeRedis

FIXTURES = Path(__file__).parent / "fixtures"
ME = "QA15JOB01"
FOREIGN = "QA15JOB02"
PASSWORD = "qa15-jobs-password"
CSRF = "qa15-csrf-token"
FORM_URL = (
    "https://selcrs.nsysu.edu.tw/menu4/addcourse/ssform.asp"
    "?X1=09&X2=0&DEG_COD=B&college=1&dept=36&grade=1&SCH_COD=2&USE_YR=115&EDU=B"
)
SECRET = "qa15-jobs-secret"


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
        ids = select(Student.id).where(Student.student_no.in_([ME, FOREIGN]))
        job_ids = select(WriteJob.id).where(WriteJob.student_id.in_(ids))
        await session.execute(delete(WriteAudit).where(WriteAudit.job_id.in_(job_ids)))
        await session.execute(delete(WriteJob).where(WriteJob.student_id.in_(ids)))
        await session.execute(delete(Student).where(Student.student_no.in_([ME, FOREIGN])))


@dataclass
class StubSso2:
    calls: list = field(default_factory=list)

    async def login_sso2(self, student_no: str, password: str, transport=None) -> Sso2Result:
        self.calls.append(student_no)
        jar = httpx.Cookies()
        jar.set("ASPSESSIONIDQATEST", f"QA15-JOB-{len(self.calls):03d}")
        return Sso2Result(outcome=Sso2Outcome.SUCCESS, cookies=jar, detail=None)


@dataclass
class StubProbe:
    async def get_studfun(self) -> str:
        return _load("studfun_open_ssform_provisional.html")

    async def get_write_form(self, form_url: str) -> str:
        assert form_url == FORM_URL
        return _load("ssform_provisional.html", "big5hkscs")


@dataclass
class Harness:
    client: TestClient
    redis: FakeRedis
    csrf: str = CSRF

    def login(self, student: str = ME) -> str:
        response = self.client.post(
            "/api/auth/login", json={"student_no": student, "password": PASSWORD}
        )
        assert response.status_code == 200, response.text
        self.csrf = response.json()["csrf_token"]
        return self.csrf

    def get_job(self, job_id: str, csrf: str | None = None):
        return self.client.get(
            f"/api/write/jobs/{job_id}", headers={"X-CSRF-Token": csrf or self.csrf}
        )


def _make_harness(monkeypatch) -> Harness:
    app = create_app(Settings(app_secret=SECRET))
    client = TestClient(app, base_url="https://testserver")
    harness = Harness(client=client, redis=FakeRedis())

    async def stub_resolve(db, *, year_sem, ident):
        return COURSE_NOT_FOUND

    monkeypatch.setattr("app.api.auth.login_sso2", StubSso2().login_sso2)
    monkeypatch.setattr("app.api.write_submit.login_sso2", StubSso2().login_sso2)
    probe = StubProbe()
    monkeypatch.setattr("app.api.write_probe.get_studfun", probe.get_studfun)
    monkeypatch.setattr("app.api.write_probe.get_write_form", probe.get_write_form)
    monkeypatch.setattr("app.api.write.resolve_course", stub_resolve)
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


async def _seed_terminal_job(
    factory, *, student: str, status: str, audits: list[tuple[str, str, str, str | None]]
) -> str:
    async with factory() as session, session.begin():
        student_id = (
            await session.execute(select(Student.id).where(Student.student_no == student))
        ).scalar_one_or_none()
        if student_id is None:
            row = Student(student_no=student)
            session.add(row)
            await session.flush()
            student_id = row.id
        ops = [
            {"action": action, "code": code, "priority": None}
            for code, action, _outcome, _msg in audits
        ]
        job = WriteJob(
            student_id=student_id,
            status=status,
            ops=ops,
            payload_hash=f"qa15job-{uuid.uuid4().hex}",
            finished_at=datetime.now(UTC),
        )
        session.add(job)
        await session.flush()
        for code, action, outcome, msg in audits:
            session.add(
                WriteAudit(
                    job_id=job.id,
                    course_id=code,
                    action=action,
                    outcome=outcome,
                    school_msg=msg,
                    payload_hash=job.payload_hash,
                    stuid_hash=audit_stuid_hash(SECRET, student),
                )
            )
        return str(job.id)


def test_unknown_or_foreign_job_is_a_flat_404(harness):
    harness.login(ME)
    assert harness.get_job(str(uuid.uuid4())).status_code == 404
    assert harness.get_job("not-a-uuid").status_code == 404


def test_owner_view_surfaces_audit_outcomes_in_canonical_order(harness):
    csrf = harness.login(ME)
    job_id = _run(
        lambda factory: _seed_terminal_job(
            factory,
            student=ME,
            status="done",
            audits=[
                ("M3046243", "-", OUTCOME_STAGE_EXPIRED, None),
                ("GEAE2526", "+", "success", "加選成功"),
                ("MEME101B", "+", "failed", "加選失敗：名額已滿（額滿）"),
            ],
        )
    )
    try:
        response = harness.get_job(job_id, csrf)
        assert response.status_code == 200
        view = response.json()
        assert view["job_id"] == job_id
        assert view["status"] == "done"
        assert view["message"] is None
        assert view["reconcile"] is None
        assert [(o["code"], o["action"], o["outcome"]) for o in view["ops"]] == [
            ("M3046243", "-", "階段逾時"),
            ("GEAE2526", "+", "success"),
            ("MEME101B", "+", "failed"),
        ]
        assert view["ops"][2]["school_msg"] == "加選失敗：名額已滿（額滿）"
        assert view["finished_at"] is not None and view["created_at"] is not None
    finally:
        pass


def test_superseded_job_carries_the_distinct_ui_message(harness):
    csrf = harness.login(ME)
    job_id = _run(
        lambda factory: _seed_terminal_job(
            factory,
            student=ME,
            status="session_superseded",
            audits=[("GEAE2526", "+", "success", "加選成功")],
        )
    )
    view = harness.get_job(job_id, csrf).json()
    assert view["status"] == "session_superseded"
    assert view["message"] == "你已在別處重新登入，此批送單已取消，請重新預檢"


def test_dwell_cancelled_job_carries_its_own_message(harness):
    csrf = harness.login(ME)
    job_id = _run(
        lambda factory: _seed_terminal_job(
            factory,
            student=ME,
            status="cancelled",
            audits=[("GEAE2526", "+", "success", "加選成功")],
        )
    )
    view = harness.get_job(job_id, csrf).json()
    assert view["status"] == "cancelled"
    assert view["message"] == "排隊逾時，此批送單已自動取消，請重新預檢"
    # A superseded job must never render the dwell copy (distinctness proof).
    assert "重新登入" not in view["message"]


def test_unknown_reconciled_ops_flag_manual_resync(harness):
    csrf = harness.login(ME)
    job_id = _run(
        lambda factory: _seed_terminal_job(
            factory,
            student=ME,
            status="done",
            audits=[
                ("GEAE2526", "+", OUTCOME_UNKNOWN_RECONCILED, "加選失敗：課程重複加選"),
                ("MEME101B", "+", "success", "加選成功"),
            ],
        )
    )
    view = harness.get_job(job_id, csrf).json()
    assert view["reconcile"] == "manual_resync_needed"


def test_foreign_students_job_is_404_not_403(harness):
    _ = harness.login(ME)
    foreign_job_id = _run(
        lambda factory: _seed_terminal_job(
            factory,
            student=FOREIGN,
            status="done",
            audits=[("GEAE2526", "+", "success", "加選成功")],
        )
    )
    view = harness.get_job(foreign_job_id)
    assert view.status_code == 404
