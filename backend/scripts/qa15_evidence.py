"""Todo-15 QA driver: scripted flows for qa/15-*.log evidence.

Runs the REAL app + REAL Postgres (compose network) with FakeRedis and the
school scripted at the adapter seams (SSO2 at app.api.auth +
app.api.write_submit, probe at app.api.write_probe, catalog at
app.api.write, engine seams at app.write.engine / app.write.reconcile). No
live school traffic, no real secrets - QA15* test students only, wiped at
start AND end so reruns stay deterministic.

Usage: docker compose -f deploy/docker-compose.yml run --rm --no-deps \
  -v "$PWD/backend:/app" -v /app/.venv worker \
  uv run --no-sync python -m scripts.qa15_evidence --scenario \
  submit|mixed|auditfail|idem|superseded|dwell|reconcile|parser|whitelist
"""

import argparse
import json
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import anyio
import httpx
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update
from sqlalchemy.exc import SQLAlchemyError

import app.write.engine as engine_mod
import app.write.reconcile as reconcile_mod
from app.config import Settings
from app.db import build_engine, build_session_factory
from app.main import create_app
from app.models.students import Student
from app.models.write import WriteAudit, WriteJob
from app.selcrs.endpoints import Sso2Result
from app.selcrs.errors import SelcrsUnavailable
from app.selcrs.sso2 import Sso2Outcome
from app.selections.parse import SelectionItem
from app.selections.store import SelectionsSnapshot, store_snapshot
from app.write import jobs as write_jobs_mod
from app.write.catalog import COURSE_NOT_FOUND, CourseInfo
from app.write.engine import EngineContext, execute_ticket
from app.write.queue import parse_ticket
from app.write.response import parse_submit_response
from tests.fake_redis import FakeRedis

FIXTURES = Path(__file__).parent.parent / "tests" / "fixtures"
STUDENT = "QA15TEST01"
PASSWORD = "qa15-password"
SECRET = "qa15-evidence-secret"
FORM_URL = (
    "https://selcrs.nsysu.edu.tw/menu4/addcourse/ssform.asp"
    "?X1=09&X2=0&DEG_COD=B&college=1&dept=36&grade=1&SCH_COD=2&USE_YR=115&EDU=B"
)
FAILURES: list[str] = []
SETTINGS = Settings(app_secret=SECRET)


def _verdict(ok: bool, label: str, detail: str = "") -> None:
    suffix = f" :: {detail}" if detail else ""
    print(f"[{'OK' if ok else 'FAIL'}] {label}{suffix}")
    if not ok:
        FAILURES.append(label)


def _load(name: str, encoding: str = "utf-8") -> str:
    return (FIXTURES / name).read_bytes().decode(encoding)


def _dbrun(step):
    async def wrapped():
        engine = build_engine(SETTINGS)
        try:
            return await step(build_session_factory(engine))
        finally:
            await engine.dispose()

    return anyio.run(wrapped)


def _wipe_all() -> None:
    students = [STUDENT, "QA15TEST02", "QA15ENG01", "QA15ARC01"]

    async def wipe(factory) -> None:
        async with factory() as session, session.begin():
            ids = select(Student.id).where(Student.student_no.in_(students))
            job_ids = select(WriteJob.id).where(WriteJob.student_id.in_(ids))
            await session.execute(delete(WriteAudit).where(WriteAudit.job_id.in_(job_ids)))
            await session.execute(delete(WriteJob).where(WriteJob.student_id.in_(ids)))
            await session.execute(delete(Student).where(Student.student_no.in_(students)))

    _dbrun(wipe)


def _ledger(job_id: uuid.UUID):
    async def step(factory):
        async with factory() as session:
            job = (
                await session.execute(select(WriteJob).where(WriteJob.id == job_id))
            ).scalar_one_or_none()
            audits = (
                (
                    await session.execute(
                        select(WriteAudit)
                        .where(WriteAudit.job_id == job_id)
                        .order_by(WriteAudit.created_at, WriteAudit.id)
                    )
                )
                .scalars()
                .all()
            )
            return job, audits

    return _dbrun(step)


async def _noop_sleep(_seconds: float) -> None:
    return None


@dataclass
class StubSso2:
    calls: list = field(default_factory=list)

    async def login_sso2(self, student_no: str, password: str, transport=None) -> Sso2Result:
        self.calls.append((student_no, password))
        jar = httpx.Cookies()
        jar.set("ASPSESSIONIDQATEST", f"QA15-COOKIE-{len(self.calls):03d}")
        return Sso2Result(outcome=Sso2Outcome.SUCCESS, cookies=jar, detail=None)


@dataclass
class StubProbe:
    async def get_studfun(self) -> str:
        return _load("studfun_open_ssform_provisional.html")

    async def get_write_form(self, form_url: str) -> str:
        assert form_url == FORM_URL
        return _load("ssform_provisional.html", "big5hkscs")


@dataclass
class ScriptedPost:
    responses: list
    after_success: Callable[[], None] | None = None
    calls: list = field(default_factory=list)

    async def post_write(self, cookies, submit_url: str, payload, *, referer: str) -> str:
        self.calls.append((submit_url, dict(payload), referer))
        item = self.responses.pop(0)
        if isinstance(item, SelcrsUnavailable):
            raise item
        if self.after_success is not None:
            self.after_success()
        return item


class Harness:
    """Real app + FakeRedis; the school is stubbed by attribute assignment."""

    def __init__(self) -> None:
        app = create_app(SETTINGS)
        self.client = TestClient(app, base_url="https://testserver")
        self.redis = FakeRedis()
        self.sso2 = StubSso2()
        self.probe = StubProbe()
        self.csrf = ""
        import app.api.auth as auth_api
        import app.api.write as write_api
        import app.api.write_submit as submit_api
        from app.api import write_probe

        auth_api.login_sso2 = self.sso2.login_sso2
        submit_api.login_sso2 = self.sso2.login_sso2
        write_probe.get_studfun = self.probe.get_studfun
        write_probe.get_write_form = self.probe.get_write_form

        async def stub_resolve(db, *, year_sem, ident):
            if ident in ("GEAE2526", "MEME101B", "M3046243"):
                return CourseInfo(
                    course_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"qa15.{ident}")),
                    code=ident, class_time=(), restrict=60, select_n=50,
                    selected_n=40, remaining=10, ingested_at="2026-08-28T03:10:00+08:00",
                )
            return COURSE_NOT_FOUND

        async def stub_resolve_ids(db, *, year_sem, course_ids):
            return {}

        write_api.resolve_course = stub_resolve
        write_api.resolve_courses_by_ids = stub_resolve_ids

    def __enter__(self):
        self.client.__enter__()
        self.client.app.state.redis = self.redis
        return self

    def __exit__(self, *exc):
        self.client.__exit__(None, None, None)

    def login(self, student: str = STUDENT) -> str:
        response = self.client.post(
            "/api/auth/login", json={"student_no": student, "password": PASSWORD}
        )
        assert response.status_code == 200, response.text
        self.csrf = response.json()["csrf_token"]
        return self.csrf

    async def seed_selections(self, codes: list[str]) -> None:
        await store_snapshot(
            self.redis,
            self.client.cookies.get("session_id"),
            SelectionsSnapshot(
                synced_at="2026-08-28T09:00:00+08:00",
                items=[
                    SelectionItem(
                        code=code, course_no="GE2526", state="選上", dept="通識",
                        name="某通識課", credit=2, compulsory_elective="選",
                        teacher="某人", room_text="", points_priority=None, stage="0",
                        year_semest_note="期", times=None, room=None,
                        unknown=True, course_id=None,
                    )
                    for code in codes
                ],
            ),
        )

    def preview(self, ops: list[dict]) -> dict:
        response = self.client.post(
            "/api/write/preview", json={"ops": ops}, headers={"X-CSRF-Token": self.csrf}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["writable"] is True, body
        return body

    def submit(self, token: str, password: str = PASSWORD):
        return self.client.post(
            "/api/write/submit",
            json={"confirm_token": token, "password": password},
            headers={"X-CSRF-Token": self.csrf},
        )

    def get_job(self, job_id: str):
        return self.client.get(
            f"/api/write/jobs/{job_id}", headers={"X-CSRF-Token": self.csrf}
        )

    async def _engine_core(
        self, ticket, post: ScriptedPost, slt_html: str = ""
    ) -> None:
        engine = build_engine(SETTINGS)
        factory = build_session_factory(engine)
        try:
            ctx = EngineContext(
                redis=self.redis, session_factory=factory, settings=SETTINGS,
                sleep=_noop_sleep,
            )

            async def get_form(cookies, form_url: str) -> str:
                return await self.probe.get_write_form(form_url)

            async def get_slt(cookies) -> str:
                return slt_html

            engine_mod.get_write_form = get_form
            engine_mod.post_write = post.post_write
            reconcile_mod.get_slt_result = get_slt
            await execute_ticket(ticket, ctx)
        finally:
            await engine.dispose()

    def run_engine(self, ticket_json: str, post: ScriptedPost, *, slt_html: str = "") -> None:
        anyio.run(self._engine_core, parse_ticket(ticket_json), post, slt_html)


def _batch() -> list[dict]:
    return [
        {"action": "+", "course_id": "GEAE2526", "priority": 1},
        {"action": "+", "course_id": "MEME101B", "priority": 2},
        {"action": "-", "course_id": "M3046243", "drop_confirm_text": "M3046243"},
    ]


async def _prepare(harness: Harness) -> dict:
    harness.login()
    await harness.seed_selections(["M3046243"])
    return harness.preview(_batch())


def scenario_submit() -> None:
    with Harness() as harness:
        body = anyio.run(_prepare, harness)
        response = harness.submit(body["confirm_token"])
        _verdict(response.status_code == 202, "submit: 2 adds + 1 drop -> 202 queued",
                 f"body={response.json()}")
        job_id = response.json()["job_id"]
        session_id = harness.client.cookies.get("session_id")
        jar = harness.redis.peek(f"selcrs:{session_id}")
        _verdict(bool(jar and "QA15-COOKIE-002" in jar),
                 "submit: fresh SSO2 jar overwrote the session's selcrs entry")
        tickets = harness.redis.lmembers("writeq:jobs")
        ticket = parse_ticket(tickets[0])
        _verdict(
            ticket is not None and ticket.session_ref == session_id and ticket.job_id == job_id,
            "submit: FIFO ticket binds job + session_ref")

        post = ScriptedPost([_load("ssprs_resp_all_ok_provisional.html")])
        harness.run_engine(tickets[0], post)
        job, audits = _ledger(uuid.UUID(job_id))
        _verdict(job.status == "done", "engine: job -> done with all ops executed")
        outcomes = {audit.course_id: audit.outcome for audit in audits}
        _verdict(
            outcomes == {"M3046243": "success", "GEAE2526": "success", "MEME101B": "success"},
            "engine: 3 audit rows, all success", json.dumps(outcomes, ensure_ascii=False))
        stuid_ok = all(len(a.stuid_hash) == 64 for a in audits) and all(
            STUDENT not in (a.school_msg or "") for a in audits
        )
        _verdict(stuid_ok, "engine: stuid_hash salted everywhere, raw id nowhere")
        _verdict(
            len(post.calls) == 1 and post.calls[0][2] == FORM_URL,
            "engine: exactly one POST with Referer:<form_url>", post.calls[0][0])
        payload = post.calls[0][1]
        _verdict(
            payload.get("D1") == "-" and payload.get("C1") == "M3046243"
            and payload.get("D2") == "+" and payload.get("C2") == "GEAE2526"
            and payload.get("T2") == "01" and payload.get("step") == "2"
            and payload.get("send") == "提交" and payload.get("MAX_ADD") == "15",
            "engine: hidden replay + D/C/T overwrite only")
        view = harness.get_job(job_id).json()
        _verdict(
            view["status"] == "done" and view["message"] is None
            and all(op["outcome"] == "success" for op in view["ops"]),
            "jobs view: done, per-op outcomes, no terminal message")


def scenario_mixed() -> None:
    with Harness() as harness:
        body = anyio.run(_prepare, harness)
        response = harness.submit(body["confirm_token"])
        job_id = response.json()["job_id"]
        post = ScriptedPost([_load("ssprs_resp_mixed_provisional.html")])
        harness.run_engine(harness.redis.lmembers("writeq:jobs")[0], post)
        job, audits = _ledger(uuid.UUID(job_id))
        outcomes = {audit.course_id: audit.outcome for audit in audits}
        _verdict(job.status == "done", "mixed: batch executed end-to-end, no rollback")
        _verdict(
            outcomes == {"GEAE2526": "success", "MEME101B": "failed", "M3046243": "failed"},
            "mixed: ok / 額滿 / 必修 mapped back by course code",
            json.dumps(outcomes, ensure_ascii=False))
        msgs = {audit.course_id: (audit.school_msg or "") for audit in audits}
        _verdict(
            "額滿" in msgs["MEME101B"] and "必修" in msgs["M3046243"],
            "mixed: school messages stored per op", f"MEME101B='{msgs['MEME101B']}'")


def scenario_auditfail() -> None:
    with Harness() as harness:
        body = anyio.run(_prepare, harness)
        response = harness.submit(body["confirm_token"])
        job_id = response.json()["job_id"]
        post = ScriptedPost([_load("ssprs_resp_all_ok_provisional.html")])

        async def broken_insert(session, **kwargs):
            raise SQLAlchemyError("scripted audit sink outage")

        original = write_jobs_mod.insert_pending_audits
        write_jobs_mod.insert_pending_audits = broken_insert
        try:
            harness.run_engine(harness.redis.lmembers("writeq:jobs")[0], post)
        finally:
            write_jobs_mod.insert_pending_audits = original
        job, audits = _ledger(uuid.UUID(job_id))
        _verdict(job.status == "failed", "auditfail: job failed-honest")
        _verdict(len(post.calls) == 0, "auditfail: ZERO school calls (fail-closed proof)")
        _verdict(audits == [], "auditfail: no half-written audit rows")


def scenario_idem() -> None:
    with Harness() as harness:
        body = anyio.run(_prepare, harness)
        created = harness.submit(body["confirm_token"])
        _verdict(created.status_code == 202, "idem: first submit -> 202")
        replay = harness.submit(body["confirm_token"])
        _verdict(
            replay.status_code == 409 and replay.json()["detail"] == "confirm_token_unknown",
            "idem: replay of the spent token -> 409")
        again = harness.preview(_batch())  # same batch re-mints the same token
        second = harness.submit(again["confirm_token"])
        _verdict(
            second.status_code == 409
            and second.json()["detail"] == "duplicate_active_job"
            and second.json()["job_id"] == created.json()["job_id"],
            "idem: re-preview+submit -> 409 carrying the existing job id",
            f"job_id={second.json()['job_id']}")
        _verdict(
            len(harness.redis.lmembers("writeq:jobs")) == 1,
            "idem: exactly one ticket ever enqueued")


def scenario_superseded() -> None:
    with Harness() as harness:
        body = anyio.run(_prepare, harness)
        created = harness.submit(body["confirm_token"])
        job_id = created.json()["job_id"]
        harness.login()  # a NEW login while the job sits queued
        job, _audits = _ledger(uuid.UUID(job_id))
        _verdict(
            job.status == "session_superseded" and job.finished_at is not None,
            "superseded: login during queued -> session_superseded")
        view = harness.get_job(job_id).json()
        _verdict(
            view["message"] == "你已在別處重新登入，此批送單已取消，請重新預檢",
            "superseded: distinct UI message", view["message"])
        post = ScriptedPost([_load("ssprs_resp_all_ok_provisional.html")])
        harness.run_engine(harness.redis.lmembers("writeq:jobs")[0], post)
        _verdict(len(post.calls) == 0, "superseded: worker never posts a superseded job")


def scenario_dwell() -> None:
    with Harness() as harness:
        body = anyio.run(_prepare, harness)
        created = harness.submit(body["confirm_token"])
        job_id = uuid.UUID(created.json()["job_id"])

        async def backdate(factory) -> None:
            async with factory() as session, session.begin():
                await session.execute(
                    update(WriteJob)
                    .where(WriteJob.id == job_id)
                    .values(created_at=datetime.now(UTC) - timedelta(seconds=660))
                )

        _dbrun(backdate)
        post = ScriptedPost([_load("ssprs_resp_all_ok_provisional.html")])
        harness.run_engine(harness.redis.lmembers("writeq:jobs")[0], post)
        job, _audits = _ledger(job_id)
        _verdict(job.status == "cancelled", "dwell: >WRITE_QUEUE_DWELL_MAX -> cancelled")
        _verdict(len(post.calls) == 0, "dwell: zero school calls")
        view = harness.get_job(str(job_id)).json()
        _verdict(
            view["message"] == "排隊逾時，此批送單已自動取消，請重新預檢",
            "dwell: cancelled carries its own message")


def scenario_reconcile() -> None:
    with Harness() as harness:
        harness.login()
        body = harness.preview([{"action": "+", "course_id": "GEAE2526", "priority": 1}])
        created = harness.submit(body["confirm_token"])
        post = ScriptedPost(
            [SelcrsUnavailable("scripted transport failure"),
             _load("ssprs_resp_dup_provisional.html")])
        harness.run_engine(
            harness.redis.lmembers("writeq:jobs")[0], post,
            slt_html=_load("slt_result_reconcile_provisional.html"))
        _job, audits = _ledger(uuid.UUID(created.json()["job_id"]))
        outcomes = {audit.course_id: audit.outcome for audit in audits}
        _verdict(
            outcomes.get("GEAE2526") == "success"
            and "對帳確認" in (audits[0].school_msg or ""),
            "reconcile: dup-like after retry upgraded to the real state",
            json.dumps(outcomes, ensure_ascii=False))

        # variant: the session dies between POST and the reconcile fetch
        body2 = harness.preview([{"action": "+", "course_id": "GEAE2526", "priority": 1}])
        created2 = harness.submit(body2["confirm_token"])
        session_id = harness.client.cookies.get("session_id")

        def drop_jar() -> None:
            harness.redis._values.pop(f"selcrs:{session_id}", None)
            harness.redis._values.pop(f"selcrs_hard:{session_id}", None)

        post2 = ScriptedPost(
            [SelcrsUnavailable("scripted transport failure"),
             _load("ssprs_resp_dup_provisional.html")],
            after_success=drop_jar)
        post2_sticky = harness.redis.lmembers("writeq:jobs")[-1]
        harness.run_engine(post2_sticky, post2)
        _job2, audits2 = _ledger(uuid.UUID(created2.json()["job_id"]))
        outcomes2 = {audit.course_id: audit.outcome for audit in audits2}
        _verdict(
            outcomes2.get("GEAE2526") == "unknown-reconciled",
            "reconcile: dead session leaves unknown-reconciled",
            json.dumps(outcomes2, ensure_ascii=False))
        view2 = harness.get_job(created2.json()["job_id"]).json()
        _verdict(
            view2.get("reconcile") == "manual_resync_needed",
            "reconcile: jobs view flags manual_resync_needed")


def scenario_parser() -> None:
    parsed = parse_submit_response(
        _load("ssprs_resp_mixed_provisional.html"), ["GEAE2526", "MEME101B", "M3046243"]
    )
    print("parser fixture: ssprs_resp_mixed_provisional.html [PROVISIONAL until live capture]")
    for code, verdict in parsed.items():
        print(f"  {code} -> {verdict.outcome} :: {(verdict.school_msg or '')[:60]}")
    _verdict(
        parsed["GEAE2526"].outcome == "success"
        and parsed["MEME101B"].outcome == "failed"
        and parsed["M3046243"].outcome == "failed",
        "parser: per-code verdict mapping locked (provisional vocab)")


def scenario_whitelist() -> None:
    with Harness() as harness:
        body = anyio.run(_prepare, harness)
        harness.submit(body["confirm_token"])
        raw = harness.redis.lmembers("writeq:jobs")[0]
        parsed = json.loads(raw)
        _verdict(
            set(parsed) == {"job_id", "session_ref", "student_no",
                            "canonical_ops", "variant", "form_url"},
            "whitelist: ticket keys == whitelist exactly")
        folded = raw.lower()
        leaked = [
            needle
            for needle in ("password", "spassword", "cookie", "secret", "csrf",
                           "jar", "bearer", "qa15-cookie")
            if needle in folded
        ]
        _verdict(leaked == [], "whitelist: no password/cookie/secret-shaped fields")


SCENARIOS = {
    "submit": scenario_submit,
    "mixed": scenario_mixed,
    "auditfail": scenario_auditfail,
    "idem": scenario_idem,
    "superseded": scenario_superseded,
    "dwell": scenario_dwell,
    "reconcile": scenario_reconcile,
    "parser": scenario_parser,
    "whitelist": scenario_whitelist,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Todo-15 QA evidence driver.")
    parser.add_argument("--scenario", required=True, choices=sorted([*SCENARIOS, "all"]))
    args = parser.parse_args()
    _wipe_all()
    try:
        for name in ([*SCENARIOS] if args.scenario == "all" else [args.scenario]):
            print(f"--- scenario: {name} ---")
            SCENARIOS[name]()
    finally:
        _wipe_all()
    print(f"RESULT: {'PASS' if not FAILURES else 'FAIL ' + ','.join(FAILURES)}")
    return 0 if not FAILURES else 1


if __name__ == "__main__":
    sys.exit(main())
