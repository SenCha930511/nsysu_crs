"""plans + plan_items persistence (plan todo 11, Scope A backend).

Ownership is enforced per query (always keyed by ``student_id``). The dep's
per-request session autobegins one transaction on first use; mutations join
THAT transaction and end it with ``session.commit()`` - so each mutation
(including the primary unset-then-set pair) commits atomically, and the
exactly-one-primary rule can never tear mid-route.
"""

import uuid
from typing import Final

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.courses import Course
from app.models.plans import PlanItem, StudentPlan
from app.models.students import Student

_DEGENERATE: Final = None  # readability alias for "no rows" returns


async def resolve_student_id(session: AsyncSession, student_no: str) -> uuid.UUID | None:
    """The persisted identity row for a student_no (created at first login)."""
    return (
        await session.execute(select(Student.id).where(Student.student_no == student_no))
    ).scalar_one_or_none()


async def list_plans(session: AsyncSession, student_id: uuid.UUID):
    """(plan, item_count) rows for one owner, oldest first (stable UI order)."""
    stmt = (
        select(StudentPlan, func.count(PlanItem.id))
        .outerjoin(PlanItem, PlanItem.plan_id == StudentPlan.id)
        .where(StudentPlan.student_id == student_id)
        .group_by(StudentPlan.id)
        .order_by(StudentPlan.created_at, StudentPlan.id)
    )
    return (await session.execute(stmt)).all()


async def get_owned_plan(
    session: AsyncSession, student_id: uuid.UUID, plan_id: uuid.UUID
) -> StudentPlan | None:
    """Ownership check + fetch: a foreign plan is indistinguishable from a
    missing one (the router maps None to 404, never 403)."""
    stmt = select(StudentPlan).where(
        StudentPlan.id == plan_id, StudentPlan.student_id == student_id
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def create_plan(
    session: AsyncSession, student_id: uuid.UUID, name: str
) -> StudentPlan:
    """Insert a plan; the very first plan of an account is auto-primary."""
    existing = (
        await session.execute(
            select(func.count())
            .select_from(StudentPlan)
            .where(StudentPlan.student_id == student_id)
        )
    ).scalar_one()
    plan = StudentPlan(student_id=student_id, name=name, is_primary=existing == 0)
    session.add(plan)
    await session.commit()
    await session.refresh(plan)
    return plan


async def rename_plan(session: AsyncSession, plan: StudentPlan, name: str) -> None:
    plan.name = name
    await session.commit()
    # onupdate=func.now() columns (updated_at) are expired by the flush;
    # refresh so post-commit attribute reads never trigger lazy IO.
    await session.refresh(plan)


async def set_primary(
    session: AsyncSession, student_id: uuid.UUID, plan: StudentPlan
) -> None:
    """Make ``plan`` the single primary: unset all others in the same tx."""
    await session.execute(
        update(StudentPlan)
        .where(StudentPlan.student_id == student_id, StudentPlan.is_primary.is_(True))
        .values(is_primary=False)
    )
    plan.is_primary = True
    await session.commit()
    await session.refresh(plan)  # see rename_plan: expire-on-flush guard


async def delete_plan(
    session: AsyncSession, student_id: uuid.UUID, plan: StudentPlan
) -> StudentPlan | None:
    """Delete the plan (items cascade). When the deleted plan was primary,
    promote the oldest remaining plan in the same transaction so the
    exactly-one-primary invariant is preserved after the delete."""
    await session.delete(plan)
    await session.flush()
    promoted = _DEGENERATE
    if plan.is_primary:
        promoted = (
            await session.execute(
                select(StudentPlan)
                .where(StudentPlan.student_id == student_id)
                .order_by(StudentPlan.created_at, StudentPlan.id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if promoted is not None:
            promoted.is_primary = True
    await session.commit()
    if promoted is not None:
        await session.refresh(promoted)  # see rename_plan: expire-on-flush guard
    return promoted


async def list_items(session: AsyncSession, plan_id: uuid.UUID) -> list[PlanItem]:
    """Items ordered by priority (NULLS LAST: unprioritized sink to the end),
    then insertion order as the tie-break."""
    stmt = (
        select(PlanItem)
        .where(PlanItem.plan_id == plan_id)
        .order_by(PlanItem.priority.asc().nullslast(), PlanItem.added_at, PlanItem.course_id)
    )
    return list((await session.execute(stmt)).scalars().all())


async def replace_items(
    session: AsyncSession,
    plan: StudentPlan,
    items: list[tuple[str, int | None]],
) -> list[PlanItem]:
    """Replace-all semantics in one transaction: wipe then re-insert.

    ``items`` is pre-validated (course_id unique, priorities unique in
    1..20 or None). Also touches plans.updated_at so the list view's
    timestamp reflects the last content edit.
    """
    await session.execute(delete(PlanItem).where(PlanItem.plan_id == plan.id))
    for course_id, priority in items:
        session.add(PlanItem(plan_id=plan.id, course_id=course_id, priority=priority))
    plan.updated_at = func.now()
    await session.commit()
    return await list_items(session, plan.id)


async def clone_plan(
    session: AsyncSession, plan: StudentPlan, *, name_max: int
) -> StudentPlan:
    """Duplicated one plan with all items into a new non-primary plan.

    Naming: ``{原稱} 副本``, truncated from the front of the original name so
    the suffix always survives the length budget. Never primary: the exact-one
    -primary invariant holds untouched.
    """
    suffix = " 副本"
    base = plan.name[: max(1, name_max - len(suffix))]
    clone = StudentPlan(
        student_id=plan.student_id,
        name=f"{base}{suffix}",
        is_primary=False,
    )
    session.add(clone)
    await session.flush()
    for item in await list_items(session, plan.id):
        session.add(
            PlanItem(plan_id=clone.id, course_id=item.course_id, priority=item.priority)
        )
    await session.commit()
    await session.refresh(clone)
    return clone


async def attach_courses(
    session: AsyncSession, items: list[PlanItem]
) -> dict[str, Course]:
    """Join stored course_id strings to catalog rows by id.

    plan_items.course_id is plain Text with no FK by schema (todo 2):
    non-UUID or stale ids simply miss the join (the API surfaces them as
    ``course: null``) instead of breaking the whole read.
    """
    uuids: list[uuid.UUID] = []
    for item in items:
        try:
            uuids.append(uuid.UUID(item.course_id))
        except ValueError:
            continue
    if not uuids:
        return {}
    rows = await session.execute(select(Course).where(Course.id.in_(uuids)))
    return {str(course.id): course for course in rows.scalars().all()}
