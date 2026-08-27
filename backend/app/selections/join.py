"""Join parsed selections against the courses catalog (plan todo 9).

Match key is ``courses.code`` for the current semester. Verified-facts item
(ii): the dplycourse catalog carries no 課程代碼, so ``courses.code`` is NULL
for every catalog row until ssform backfill - the join will therefore match
NOTHING in practice for now, and that MUST be a non-event: unmatched and
code-less rows keep ``unknown=True`` and are NEVER dropped (the selections
list is the student's own ground truth, the catalog join is enrichment).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.courses import Course
from app.selections.parse import SelectionItem


async def attach_course_matches(
    db: AsyncSession, *, year_sem: str, items: list[SelectionItem]
) -> list[SelectionItem]:
    """Flip ``unknown``/``course_id`` for rows whose code exists in the catalog."""
    codes = {item.code for item in items if item.code is not None}
    matched: dict[str, str] = {}
    if codes:
        rows = await db.execute(
            select(Course.id, Course.code).where(
                Course.year_sem == year_sem, Course.code.in_(sorted(codes))
            )
        )
        matched = {code: str(course_id) for course_id, code in rows if code is not None}
    return [
        item.model_copy(
            update={
                "course_id": matched.get(item.code) if item.code is not None else None,
                "unknown": item.code not in matched,
            }
        )
        for item in items
    ]
