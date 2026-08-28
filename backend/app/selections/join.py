"""Join parsed selections against the courses catalog (plan todo 9).

Match key is ``courses.code`` for the current semester — since 2026-08-28
that column holds the **課別代號** (CSE515/STP101, derived from each row's
showoutline ``CrsDat=``), which the write form (ssform C-field) accepts,
live-probed today: CSE515 resolves at chk_crsno_desc.asp, 課程代碼
(M3046243) does not. Selections keys therefore prefer ``course_no`` (the
短碼 課號 that slt_result always carries) with ``code`` as a legacy fallback.
Unmatched rows keep ``unknown=True`` and are NEVER dropped - the selections
list is the student's own ground truth, the catalog join is enrichment.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.courses import Course
from app.selections.parse import SelectionItem


async def attach_course_matches(
    db: AsyncSession, *, year_sem: str, items: list[SelectionItem]
) -> list[SelectionItem]:
    """Flip ``unknown``/``course_id`` for rows whose 課別代號 exists in the catalog."""
    wanted = {
        (item.course_no or item.code)
        for item in items
        if (item.course_no or item.code) is not None
    }
    matched: dict[str, str] = {}
    if wanted:
        rows = await db.execute(
            select(Course.id, Course.code).where(
                Course.year_sem == year_sem, Course.code.in_(sorted(wanted))
            )
        )
        matched = {code: str(course_id) for course_id, code in rows if code is not None}
    return [
        item.model_copy(
            update={
                "course_id": (
                    matched.get(item.course_no or item.code or "")
                    if (item.course_no or item.code) is not None
                    else None
                ),
                "unknown": (item.course_no or item.code) not in matched,
            }
        )
        for item in items
    ]
