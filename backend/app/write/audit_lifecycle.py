"""write_audit PII lifecycle (plan todo 15 / Scope: 熱層 90 天 → 去識別 gz
歸檔 1 年 → 刪除；學號以加鹽 hash 關聯).

Two transitions, both idempotent and reportable in dry-run:

1. **Hot → archive (default 90 days)**: rows older than the hot window are
   written DE-IDENTIFIED into one gzip JSONL archive per run —
   ``stuid_hash`` is kept (it is already the salted hash; correlation
   survives without the raw number), ``school_msg`` is reduced to an
   80-char excerpt (the raw message leaves every store after archive
   deletion) — then a write_audit_archive_meta ledger row lands and the hot
   rows are DELETED from write_audit. File first, then one transaction for
   meta + row deletion: a failed file write archives nothing.
2. **Archive → delete (1 further year)**: archive files older than the
   retention window are deleted from disk and their meta rows are marked
   ``deleted_after_1y`` (the meta ledger itself is never dropped).
"""

import gzip
import json
import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.write import WriteAudit, WriteAuditArchiveMeta

_logger = logging.getLogger(__name__)

#: school_msg excerpt length inside the redacted archive (原文摘錄 only).
ARCHIVE_MSG_EXCERPT: Final = 80

_DELETED_NOTE: Final = "deleted_after_1y"


@dataclass(frozen=True, slots=True)
class LifecycleReport:
    dry_run: bool
    hot_cutoff: str
    hot_expired_rows: int
    archive_path: str | None
    archive_cutoff: str
    archives_deleted: int


def _redacted_row(row: WriteAudit) -> dict[str, object]:
    """The archive's de-identified JSONL line for one hot row."""
    school_msg = row.school_msg or ""
    return {
        "id": str(row.id),
        "job_id": str(row.job_id),
        "course_id": row.course_id,
        "action": row.action,
        "outcome": row.outcome,
        "school_msg_excerpt": school_msg[:ARCHIVE_MSG_EXCERPT],
        "payload_hash": row.payload_hash,
        "stuid_hash": row.stuid_hash,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "archived_at": row.archived_at.isoformat() if row.archived_at else None,
    }


def _write_archive(rows: list[WriteAudit], archive_dir: Path, moment: datetime) -> Path:
    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = moment.strftime("%Y%m%d_%H%M%S")
    path = archive_dir / f"write_audit_{stamp}_{uuid.uuid4().hex[:8]}.jsonl.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(_redacted_row(row), ensure_ascii=False) + "\n")
    return path


async def _hot_rows(session: AsyncSession, *, older_than: datetime) -> list[WriteAudit]:
    return list(
        (
            await session.execute(
                select(WriteAudit).where(
                    WriteAudit.archived_at.is_(None),
                    WriteAudit.created_at < older_than,
                )
            )
        )
        .scalars()
        .all()
    )


async def _expired_metas(session: AsyncSession, *, older_than: datetime) -> list[WriteAuditArchiveMeta]:
    return list(
        (
            await session.execute(
                select(WriteAuditArchiveMeta).where(
                    WriteAuditArchiveMeta.archived_at < older_than,
                    WriteAuditArchiveMeta.note.is_distinct_from(_DELETED_NOTE),
                )
            )
        )
        .scalars()
        .all()
    )


async def run_lifecycle(
    session: AsyncSession,
    *,
    archive_dir: Path,
    hot_days: int,
    archive_days: int,
    dry_run: bool,
    now: datetime | None = None,
) -> LifecycleReport:
    """Run both transitions once. ``session`` commits only when applying."""
    moment = now if now is not None else datetime.now(UTC)
    hot_cutoff = moment - timedelta(days=hot_days)
    archive_cutoff = moment - timedelta(days=archive_days)

    hot_rows = await _hot_rows(session, older_than=hot_cutoff)
    archive_path: str | None = None
    if hot_rows and not dry_run:
        path = _write_archive(hot_rows, archive_dir, moment)
        archive_path = str(path)
        row_ids = [row.id for row in hot_rows]
        session.add(WriteAuditArchiveMeta(rows=len(hot_rows), path=str(path), note="hot_90d"))
        await session.execute(delete(WriteAudit).where(WriteAudit.id.in_(row_ids)))
        await session.commit()

    expired = await _expired_metas(session, older_than=archive_cutoff)
    deleted = 0
    if expired and not dry_run:
        for meta in expired:
            file_path = Path(meta.path)
            if file_path.exists():
                file_path.unlink()
                deleted += 1
            else:
                _logger.info("archive file already gone, marking meta only: %s", meta.path)
            meta.note = _DELETED_NOTE
        await session.commit()

    return LifecycleReport(
        dry_run=dry_run,
        hot_cutoff=hot_cutoff.isoformat(),
        hot_expired_rows=len(hot_rows),
        archive_path=archive_path,
        archive_cutoff=archive_cutoff.isoformat(),
        archives_deleted=deleted,
    )


def report_lines(report: LifecycleReport) -> list[str]:
    """The CLI's printable summary (`asdict` mirrors into JSON logs)."""
    asdict(report)  # pin serializability for the ops tooling
    mode = "DRY-RUN" if report.dry_run else "APPLY"
    return [
        f"mode: {mode}",
        f"hot cutoff (archived_at null, created_at <): {report.hot_cutoff}",
        f"hot rows to archive: {report.hot_expired_rows}",
        f"archive written: {report.archive_path or '(none)'}",
        f"archive-retention cutoff (archived_at <): {report.archive_cutoff}",
        f"archive files deleted: {report.archives_deleted}",
    ]
