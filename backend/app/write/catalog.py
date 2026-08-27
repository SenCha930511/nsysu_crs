"""Catalog lookups for the write path (plan todo 14 checks 3/4/5).

``CourseInfo`` is the boundary value the preview evaluator consumes: a
catalog row distilled to what checks need (identity, timetable, quota
snapshot), or the all-None "not resolvable" shape when the ident matches no
current-semester row - which the evaluator renders as the 無課號 verdict
(code-less rows and unknown idents are the same non-submittable thing, per
the plan's 缺碼行為規格).
"""

import uuid
from dataclasses import dataclass, field
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.courses import Course


@dataclass(frozen=True, slots=True)
class CourseInfo:
    """One catalog row as preview checks need it (never raises on missing)."""

    course_id: str | None
    code: str | None
    class_time: tuple[str, ...] = field(default_factory=tuple)
    restrict: int | None = None
    select_n: int | None = None
    selected_n: int | None = None
    remaining: int | None = None
    ingested_at: str | None = None


#: The "no such course" shape (course_id/code None drives 無課號 downstream).
COURSE_NOT_FOUND: Final = CourseInfo(course_id=None, code=None)


def _info(row: Course) -> CourseInfo:
    return CourseInfo(
        course_id=str(row.id),
        code=row.code.strip() if row.code is not None else None,
        class_time=tuple(row.class_time or ()),
        restrict=row.restrict,
        select_n=row.select_n,
        selected_n=row.selected_n,
        remaining=row.remaining,
        ingested_at=row.ingested_at.isoformat() if row.ingested_at is not None else None,
    )


async def resolve_course(
    db: AsyncSession, *, year_sem: str, ident: str
) -> CourseInfo:
    """One op's catalog row by uuid OR school code, current semester only.

    The semester filter is part of identity here: a foreign-semester row is
    as non-submittable as a missing one (submissions are always against the
    current catalog).
    """
    ident = ident.strip()
    row: Course | None = None
    try:
        course_uuid = uuid.UUID(ident)
    except ValueError:
        course_uuid = None
    if course_uuid is not None:
        row = (
            await db.execute(
                select(Course).where(Course.id == course_uuid, Course.year_sem == year_sem)
            )
        ).scalar_one_or_none()
    else:
        row = (
            await db.execute(
                select(Course).where(Course.code == ident, Course.year_sem == year_sem)
            )
        ).scalar_one_or_none()
    return _info(row) if row is not None else COURSE_NOT_FOUND


async def resolve_courses_by_ids(
    db: AsyncSession, *, year_sem: str, course_ids: list[str]
) -> dict[str, CourseInfo]:
    """Batch lookup for selections clash targets (course_id uuid strings)."""
    uuids: list[uuid.UUID] = []
    for raw in course_ids:
        try:
            uuids.append(uuid.UUID(raw))
        except ValueError:
            continue
    if not uuids:
        return {}
    rows = await db.execute(
        select(Course).where(Course.id.in_(uuids), Course.year_sem == year_sem)
    )
    return {str(row.id): _info(row) for row in rows.scalars().all()}
