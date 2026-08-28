"""Postgres side of the write queue (plan todo 15).

write_jobs is the durable ledger (partial unique index on payload_hash over
queued/running gives atomic idempotency); write_audit is the per-op outcome
ledger with the fail-closed contract: ``insert_pending_audits`` runs BEFORE
any school contact, and the engine never posts to the school while the
audit sink is known-broken. ``audit_stuid_hash`` is the salted correlation
key — sha256(APP_SECRET + '|' + student_no), stable per student (the
archive keeps this hashed form; the raw student number is never written).
"""

import hashlib
import uuid
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.students import Student
from app.models.write import WriteAudit, WriteJob
from app.write.canonical import CanonicalOp
from app.write.outcomes import OUTCOME_PENDING

_ACTIVE_STATUSES = ("queued", "running")


class DuplicateActiveJob(Exception):
    """The partial unique index rejected an insert (a same-hash job is
    queued/running); the API maps this to 409 with the existing job id."""

    def __init__(self, payload_hash: str) -> None:
        super().__init__(f"active job already exists for payload {payload_hash!r}")
        self.payload_hash = payload_hash


def op_dict(op: CanonicalOp) -> dict[str, object]:
    """One op in its write_jobs.ops JSONB shape (never secret-bearing)."""
    return {"action": op.action, "code": op.code, "priority": op.priority}


def audit_stuid_hash(app_secret: str, student_no: str) -> str:
    """Salted correlation key for write_audit (salt = APP_SECRET)."""
    return hashlib.sha256(f"{app_secret}|{student_no}".encode()).hexdigest()


async def find_student_id(session: AsyncSession, student_no: str) -> uuid.UUID | None:
    return (
        await session.execute(select(Student.id).where(Student.student_no == student_no))
    ).scalar_one_or_none()


async def find_active_job_by_hash(session: AsyncSession, payload_hash: str) -> WriteJob | None:
    """The queued/running job carrying ``payload_hash``, if any (fast-path
    duplicate check; the partial unique index is the atomic backstop)."""
    return (
        await session.execute(
            select(WriteJob).where(
                WriteJob.payload_hash == payload_hash,
                WriteJob.status.in_(_ACTIVE_STATUSES),
            )
        )
    ).scalar_one_or_none()


async def create_queued_job(
    session: AsyncSession,
    *,
    student_id: uuid.UUID,
    ops: list[CanonicalOp],
    payload_hash: str,
) -> WriteJob:
    """Insert the queued job row; DuplicateActiveJob on the index's race.

    Raises during flush inside the caller's transaction - the caller rolls
    back and re-reads ``find_active_job_by_hash`` for the 409 body.
    """
    job = WriteJob(
        student_id=student_id,
        status="queued",
        ops=[op_dict(op) for op in ops],
        payload_hash=payload_hash,
    )
    session.add(job)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise DuplicateActiveJob(payload_hash) from exc
    return job


async def claim_job(
    session: AsyncSession, job_id: uuid.UUID, *, not_older_than: datetime
) -> WriteJob | None:
    """Atomic queued -> running transition (dwelling jobs and already
    terminal/superseded jobs are NOT claimed - None back both ways)."""
    return (
        await session.execute(
            update(WriteJob)
            .where(
                WriteJob.id == job_id,
                WriteJob.status == "queued",
                WriteJob.created_at >= not_older_than,
            )
            .values(status="running", started_at=func.now())
            .returning(WriteJob)
        )
    ).scalar_one_or_none()


async def read_job_status(session: AsyncSession, job_id: uuid.UUID) -> str | None:
    return (
        await session.execute(select(WriteJob.status).where(WriteJob.id == job_id))
    ).scalar_one_or_none()


async def read_job(session: AsyncSession, job_id: uuid.UUID) -> WriteJob | None:
    return (
        await session.execute(select(WriteJob).where(WriteJob.id == job_id))
    ).scalar_one_or_none()


async def finish_job(session: AsyncSession, job_id: uuid.UUID, status: str) -> bool:
    """Terminal write guarded non-terminal-only: a session_superseded job
    (flipped by a new login) is never clobbered back to done/failed."""
    result = await session.execute(
        update(WriteJob)
        .where(WriteJob.id == job_id, WriteJob.status.in_(_ACTIVE_STATUSES))
        .values(status=status, finished_at=func.now())
    )
    return bool(getattr(result, "rowcount", 0) or 0)


async def cancel_stale_active_jobs(session: AsyncSession, *, older_than: datetime) -> int:
    """Dwell guard: queued/running jobs older than the cutoff -> cancelled."""
    result = await session.execute(
        update(WriteJob)
        .where(WriteJob.status.in_(_ACTIVE_STATUSES), WriteJob.created_at < older_than)
        .values(status="cancelled", finished_at=func.now())
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def insert_pending_audits(
    session: AsyncSession,
    *,
    job_id: uuid.UUID,
    ops: list[CanonicalOp],
    payload_hash: str,
    stuid_hash: str,
) -> list[uuid.UUID]:
    """Fail-closed pre-insert: one pending row per op, ids in op order.

    Runs BEFORE any school contact; if it raises, the engine fails the job
    without ever calling the school (the audit sink being writable is a
    precondition of posting, not an afterthought).
    """
    audits = [
        WriteAudit(
            job_id=job_id,
            course_id=op.code,
            action=op.action,
            outcome=OUTCOME_PENDING,
            school_msg=None,
            payload_hash=payload_hash,
            stuid_hash=stuid_hash,
        )
        for op in ops
    ]
    session.add_all(audits)
    await session.flush()
    return [audit.id for audit in audits]


async def apply_audit_outcomes(
    session: AsyncSession, updates: list[tuple[uuid.UUID, str, str | None]]
) -> None:
    """Write back (outcome, school_msg) per audit id after the batch POST."""
    for audit_id, outcome, school_msg in updates:
        await session.execute(
            update(WriteAudit)
            .where(WriteAudit.id == audit_id)
            .values(outcome=outcome, school_msg=school_msg)
        )


async def load_job_for_owner(
    session: AsyncSession, job_id: uuid.UUID, student_id: uuid.UUID
) -> WriteJob | None:
    """Owner-scoped job read (a foreign job is indistinguishable from a
    missing one - the API renders both as the same 404)."""
    return (
        await session.execute(
            select(WriteJob).where(
                WriteJob.id == job_id, WriteJob.student_id == student_id
            )
        )
    ).scalar_one_or_none()


async def load_jobs_for_owner(
    session: AsyncSession, student_id: uuid.UUID, *, limit: int
) -> list[WriteJob]:
    """Newest-first job rows for the records page (owner scope, stable ties)."""
    return list(
        (
            await session.execute(
                select(WriteJob)
                .where(WriteJob.student_id == student_id)
                .order_by(WriteJob.created_at.desc(), WriteJob.id.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )


async def load_audits(session: AsyncSession, job_id: uuid.UUID) -> list[WriteAudit]:
    return list(
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


async def load_audits_for_jobs(
    session: AsyncSession, job_ids: list[uuid.UUID]
) -> list[WriteAudit]:
    """Audit rows for a batch of job ids (empty fast-path stays empty)."""
    if not job_ids:
        return []
    return list(
        (
            await session.execute(
                select(WriteAudit)
                .where(WriteAudit.job_id.in_(job_ids))
                .order_by(WriteAudit.created_at, WriteAudit.id)
            )
        )
        .scalars()
        .all()
    )
