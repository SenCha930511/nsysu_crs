"""write_audit PII lifecycle tests (plan todo 15 deliverable 4): hot rows
age into a redacted gzip archive with the salted hash kept and school_msg
reduced to an excerpt, the meta ledger records the archive, and archives
themselves are deleted after the retention year. Real compose Postgres,
synthetic QA15ARC rows only, tmp archive dirs."""

import gzip
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import anyio
import pytest
from sqlalchemy import delete, select

from app.config import Settings
from app.db import build_engine, build_session_factory
from app.models.students import Student
from app.models.write import WriteAudit, WriteAuditArchiveMeta, WriteJob
from app.write.audit_lifecycle import (
    ARCHIVE_MSG_EXCERPT,
    _redacted_row,
    report_lines,
    run_lifecycle,
)
from app.write.jobs import audit_stuid_hash

ME = "QA15ARC01"
SECRET = "qa15-arc-secret"
NOW = datetime(2026, 8, 28, 12, 0, 0, tzinfo=UTC)


def _engine_factory():
    engine = build_engine(Settings())
    return engine, build_session_factory(engine)


def _db_available() -> bool:
    async def probe() -> bool:
        engine, factory = _engine_factory()
        try:
            async with factory() as session:
                await session.execute(select(1))
            return True
        finally:
            await engine.dispose()

    try:
        return anyio.run(probe)
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _db_available(), reason="compose Postgres unreachable")


async def _wipe(factory) -> None:
    async with factory() as session, session.begin():
        ids = select(Student.id).where(Student.student_no == ME)
        job_ids = select(WriteJob.id).where(WriteJob.student_id.in_(ids))
        await session.execute(delete(WriteAudit).where(WriteAudit.job_id.in_(job_ids)))
        await session.execute(delete(WriteJob).where(WriteJob.student_id.in_(ids)))
        await session.execute(delete(Student).where(Student.student_no == ME))
        await session.execute(
            delete(WriteAuditArchiveMeta).where(
                WriteAuditArchiveMeta.note.like("qa15arc%")
            )
        )


async def _seed_rows(factory, *, ages_days: list[int], msg: str | None = None) -> list[uuid.UUID]:
    async with factory() as session, session.begin():
        student = Student(student_no=ME)
        session.add(student)
        await session.flush()
        job = WriteJob(
            student_id=student.id,
            status="done",
            ops=[{"action": "+", "code": "GEAE2526", "priority": 1}],
            payload_hash=f"qa15arc-{uuid.uuid4().hex}",
        )
        session.add(job)
        await session.flush()
        ids = []
        for index, age in enumerate(ages_days):
            row = WriteAudit(
                job_id=job.id,
                course_id=f"C{index:07d}",
                action="+",
                outcome="success",
                school_msg=msg if msg is not None else "加選成功（完整原始訊息）" * 20,
                payload_hash=job.payload_hash,
                stuid_hash=audit_stuid_hash(SECRET, ME),
                created_at=NOW - timedelta(days=age),
            )
            session.add(row)
            await session.flush()
            ids.append(row.id)
        return ids


@pytest.fixture
async def db():
    engine, factory = _engine_factory()
    await _wipe(factory)
    yield factory
    await _wipe(factory)
    await engine.dispose()


@pytest.mark.anyio
async def test_dry_run_reports_without_touching_anything(db, tmp_path):
    ids = await _seed_rows(db, ages_days=[100, 10])
    async with db() as session:
        report = await run_lifecycle(
            session, archive_dir=tmp_path, hot_days=90, archive_days=365, dry_run=True, now=NOW
        )
    assert report.dry_run is True
    assert report.hot_expired_rows == 1  # only the 100-day-old row is hot-expired
    assert report.archive_path is None
    assert list(tmp_path.iterdir()) == []
    async with db() as session:
        survivors = (
            await session.execute(select(WriteAudit.id).where(WriteAudit.id.in_(ids)))
        ).scalars().all()
    assert len(survivors) == 2  # nothing deleted


@pytest.mark.anyio
async def test_apply_archives_redacted_and_deletes_hot_rows(db, tmp_path):
    full_msg = "加選失敗：名額已滿（額滿）" * 30  # way past the excerpt limit
    ids = await _seed_rows(db, ages_days=[100, 10], msg=full_msg)
    async with db() as session:
        report = await run_lifecycle(
            session, archive_dir=tmp_path, hot_days=90, archive_days=365, dry_run=False, now=NOW
        )
        await session.commit()

    assert report.hot_expired_rows == 1
    assert report.archive_path is not None
    archive = Path(report.archive_path)
    assert archive.exists() and archive.suffix == ".gz"
    with gzip.open(archive, "rt", encoding="utf-8") as handle:
        lines = [json.loads(line) for line in handle.read().splitlines()]
    assert len(lines) == 1
    row = lines[0]
    assert row["id"] == str(ids[0])
    # De-identified: hashed student key kept for correlation; msg excerpted only.
    assert row["stuid_hash"] == audit_stuid_hash(SECRET, ME)
    assert row["school_msg_excerpt"] == full_msg[:ARCHIVE_MSG_EXCERPT]
    assert "school_msg" not in row  # the RAW message left every store
    assert row["outcome"] == "success" and row["payload_hash"]

    async with db() as session:
        hot = (
            await session.execute(select(WriteAudit.id).where(WriteAudit.id.in_(ids)))
        ).scalars().all()
        metas = (
            await session.execute(
                select(WriteAuditArchiveMeta).where(WriteAuditArchiveMeta.path == str(archive))
            )
        ).scalars().all()
    assert sorted(str(i) for i in hot) == [str(ids[1])]  # only the fresh row stays hot
    assert len(metas) == 1 and metas[0].rows == 1 and metas[0].note == "hot_90d"


@pytest.mark.anyio
async def test_archive_files_age_out_and_are_deleted_with_meta_marked(db, tmp_path):
    archive = tmp_path / "old_archive.jsonl.gz"
    archive.write_bytes(gzip.compress(b"{}\n"))
    async with db() as session, session.begin():
        session.add(
            WriteAuditArchiveMeta(
                archived_at=NOW - timedelta(days=400),
                rows=1,
                path=str(archive),
                note="qa15arc-old",
            )
        )
    async with db() as session, session.begin():
        session.add(
            WriteAuditArchiveMeta(
                archived_at=NOW - timedelta(days=100),
                rows=1,
                path=str(tmp_path / "fresh.jsonl.gz"),
                note="qa15arc-fresh",
            )
        )

    async with db() as session:
        report = await run_lifecycle(
            session, archive_dir=tmp_path, hot_days=90, archive_days=365, dry_run=False, now=NOW
        )

    assert report.archives_deleted == 1
    assert not archive.exists()
    async with db() as session:
        notes = (
            (
                await session.execute(
                    select(WriteAuditArchiveMeta.note, WriteAuditArchiveMeta.path)
                )
            )
            .all()
        )
    note_by_path = {path: note for note, path in notes}
    assert note_by_path[str(archive)] == "deleted_after_1y"
    assert note_by_path[str(tmp_path / "fresh.jsonl.gz")] == "qa15arc-fresh"


@pytest.mark.anyio
async def test_dry_run_does_not_delete_archives(db, tmp_path):
    archive = tmp_path / "old.jsonl.gz"
    archive.write_bytes(gzip.compress(b"{}\n"))
    async with db() as session, session.begin():
        session.add(
            WriteAuditArchiveMeta(
                archived_at=NOW - timedelta(days=400),
                rows=1,
                path=str(archive),
                note="qa15arc-old",
            )
        )
    async with db() as session:
        report = await run_lifecycle(
            session, archive_dir=tmp_path, hot_days=90, archive_days=365, dry_run=True, now=NOW
        )
    assert report.archives_deleted == 0
    assert archive.exists()
    assert "DRY-RUN" in report_lines(report)[0]


def test_redacted_row_shape_keeps_the_hashed_correlation_key():
    row = WriteAudit(
        job_id=uuid.uuid4(),
        course_id="GEAE2526",
        action="+",
        outcome="success",
        school_msg="x" * 500,
        payload_hash="p" * 64,
        stuid_hash="s" * 64,
    )
    redacted = _redacted_row(row)
    assert redacted["stuid_hash"] == "s" * 64
    assert redacted["school_msg_excerpt"] == "x" * ARCHIVE_MSG_EXCERPT
    assert set(redacted) == {
        "id", "job_id", "course_id", "action", "outcome",
        "school_msg_excerpt", "payload_hash", "stuid_hash", "created_at", "archived_at",
    }
