"""write_jobs + write_audit(+ archive meta): the whole write path's ledger.

write_jobs.payload_hash gets a PARTIAL unique index over ('queued','running')
so a double-click / replay can never enqueue twice (DB-level idempotency).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

WRITE_JOB_STATUSES: tuple[str, ...] = (
    "queued",
    "running",
    "done",
    "failed",
    "cancelled",
    "session_superseded",
)

_STATUS_CHECK_SQL = "status IN ('queued', 'running', 'done', 'failed', 'cancelled', 'session_superseded')"
_ACTIVE_PAYLOAD_WHERE_SQL = "status IN ('queued', 'running')"

ACTIVE_PAYLOAD_INDEX_NAME = "uq_write_jobs_active_payload_hash"


class WriteJob(Base):  # noqa: MUTABLE_OK  (SQLAlchemy ORM rows are mutable by design)
    """One queued/running/finished batch of add/drop/wish operations."""

    __tablename__ = "write_jobs"
    __table_args__ = (
        CheckConstraint(_STATUS_CHECK_SQL, name="ck_write_jobs_status_valid"),
        Index(
            ACTIVE_PAYLOAD_INDEX_NAME,
            "payload_hash",
            unique=True,
            postgresql_where=text(_ACTIVE_PAYLOAD_WHERE_SQL),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id", name="fk_write_jobs_student_id_students"),
        index=True,
    )
    status: Mapped[str] = mapped_column(Text)
    ops: Mapped[list[dict[str, str]]] = mapped_column(JSONB)
    payload_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WriteAudit(Base):  # noqa: MUTABLE_OK  (SQLAlchemy ORM rows are mutable by design)
    """Per-course outcome of one job; stuid_hash is salted, never the raw id."""

    __tablename__ = "write_audit"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("write_jobs.id", name="fk_write_audit_job_id_write_jobs"),
        index=True,
    )
    course_id: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(Text)
    school_msg: Mapped[str | None] = mapped_column(Text)
    payload_hash: Mapped[str] = mapped_column(Text)
    stuid_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WriteAuditArchiveMeta(Base):  # noqa: MUTABLE_OK  (SQLAlchemy ORM rows are mutable by design)
    """Ledger of PII lifecycle archives (hot 90d -> de-identified gz 1y -> delete)."""

    __tablename__ = "write_audit_archive_meta"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=func.gen_random_uuid()
    )
    archived_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    rows: Mapped[int | None] = mapped_column(Integer)
    path: Mapped[str] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
