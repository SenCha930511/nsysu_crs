"""Atomic catalog snapshot persistence + the ingest_runs ledger (todo 6).

Snapshot contract (plan): a SUCCESSFUL ingest replaces the semester's rows
atomically - upsert matched rows in place, insert novel rows, delete rows
that vanished from the catalog - inside ONE transaction, so a mid-persist
failure rolls everything back and the previous snapshot stays servable. A
FAILED ingest never opens the courses transaction at all; it only closes the
ledger row with ok=false + the error message (never a half-truncated table).

Identity rules (documented choice, see rows.CatalogRow):
- ``code`` present  -> match on the school's ``unique(year_sem, code)``
  constraint (the DB constraint stays as the backstop; matching is done
  in-memory after pre-loading the semester because the ingest is a
  process-wide singleton behind the Redis lock).
- ``code`` NULL     -> match on the fallback key
  (year_sem, dept, name_zh, teacher, room, class_time); Postgres treats
  NULL codes as distinct, so the constraint cannot drive these rows.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.catalog.rows import CatalogRow
from app.models.courses import Course, IngestRun

#: Ledger error column guard: bounded messages keep the table lean.
_ERROR_MAX_CHARS: Final = 4000


@dataclass(frozen=True, slots=True)
class PersistOutcome:
    """What one successful snapshot replacement did."""

    rows_stored: int
    rows_updated: int
    rows_inserted: int
    rows_deleted: int
    dedup_skipped: int


_COURSE_FIELDS: Final = (
    "year_sem", "code", "dept", "grade", "class_", "name_zh", "name_en",
    "credit", "compulsory", "restrict", "select_n", "selected_n", "remaining",
    "teacher", "room", "description", "tags", "english", "change",
    "change_desc", "url",
)


def _row_payload(row: CatalogRow) -> dict[str, object]:
    payload = {field: getattr(row, field) for field in _COURSE_FIELDS}
    payload["class_time"] = list(row.class_time)
    payload["tags"] = list(row.tags)
    return payload


def _course_fallback_key(course: Course) -> tuple[object, ...]:
    class_time = course.class_time if course.class_time is not None else []
    return (
        course.year_sem,
        course.dept,
        course.name_zh,
        course.teacher,
        course.room,
        tuple(class_time),
    )


def _apply_payload(course: Course, row: CatalogRow) -> None:
    for field in _COURSE_FIELDS:
        if field == "tags":
            setattr(course, field, list(row.tags))
        else:
            setattr(course, field, getattr(row, field))
    course.class_time = list(row.class_time)
    course.ingested_at = func.now()


async def replace_year_sem_snapshot(
    session: AsyncSession,
    year_sem: str,
    rows: Sequence[CatalogRow],
) -> PersistOutcome:
    """Replace ``year_sem``'s rows atomically. CALLER owns the transaction
    boundary (``async with session.begin()``); any exception rolls back."""
    existing = (
        await session.execute(select(Course).where(Course.year_sem == year_sem))
    ).scalars().all()
    coded = {course.code: course for course in existing if course.code is not None}
    uncoded = {
        _course_fallback_key(course): course
        for course in existing
        if course.code is None
    }
    seen_identity: set[tuple[str, object]] = set()  # dedup within one scrape
    updated = inserted = dedup_skipped = 0

    for row in rows:
        identity = ("code", row.code) if row.code is not None else ("fb", row.fallback_key())
        if identity in seen_identity:
            dedup_skipped += 1  # duplicate within this scrape; first wins
            continue
        seen_identity.add(identity)
        if row.code is not None:
            target = coded.get(row.code)
            if target is not None:
                _apply_payload(target, row)
                updated += 1
            else:
                session.add(Course(**_row_payload(row)))
                inserted += 1
            continue
        key = row.fallback_key()
        target = uncoded.get(key)
        if target is not None:
            _apply_payload(target, row)
            updated += 1
        else:
            session.add(Course(**_row_payload(row)))
            inserted += 1

    # Snapshot replacement: "kept" is what THIS scrape saw - existing DB
    # rows whose identity did not show up vanished from the catalog and go.
    kept_codes = {code for kind, code in seen_identity if kind == "code"}
    kept_fallbacks = {key for kind, key in seen_identity if kind == "fb"}
    deleted = 0
    for course in existing:
        if course.code is not None:
            if course.code in kept_codes:
                continue
        elif _course_fallback_key(course) in kept_fallbacks:
            continue
        await session.delete(course)
        deleted += 1

    return PersistOutcome(
        rows_stored=updated + inserted,
        rows_updated=updated,
        rows_inserted=inserted,
        rows_deleted=deleted,
        dedup_skipped=dedup_skipped,
    )


async def open_ingest_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> uuid.UUID:
    """Ledger row for a new round (ok=false until proven otherwise)."""
    async with session_factory() as session, session.begin():
        run = IngestRun(source="self-scrape", ok=False)
        session.add(run)
        await session.flush()
        return run.id


async def close_ingest_run(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID,
    *,
    ok: bool,
    rows: int | None,
    error: str | None,
) -> None:
    """Close the ledger row. Committed in its OWN transaction (never bundled
    with the courses mutation) so a crashed round still leaves ok=false."""
    async with session_factory() as session, session.begin():
        run = await session.get(IngestRun, run_id)
        assert run is not None, f"ingest_runs row {run_id} vanished mid-run"
        run.finished_at = func.now()
        run.ok = ok
        run.rows = rows
        run.error = error[:_ERROR_MAX_CHARS] if error is not None else None
