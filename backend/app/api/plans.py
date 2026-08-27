"""Session-gated plans API (plan todo 11, Scope A backend).

Routes (all require a site session -> 401 ``not_authenticated`` when absent):
    GET    /api/plans              list my plans (oldest first) + item_count
    POST   /api/plans              create; the FIRST plan is auto-primary
    PATCH  /api/plans/{id}         rename and/or set primary (one transaction
                                   unsetting the previous primary)
    DELETE /api/plans/{id}         delete; deleting the primary auto-promotes
                                   the oldest remaining plan (same transaction)
    GET    /api/plans/{id}/items   items + embedded catalog course (null when
                                   the stored id matches no catalog row)
    PUT    /api/plans/{id}/items   replace-all items {course_id, priority?}

Ownership: every plan lookup is keyed by (plan_id, current student); a foreign
id is a flat 404 ``plan_not_found`` (never 403 - presence is not disclosed).

Items contract: priorities are int 1..20 or null (unprioritized). Within one
PUT request, course_id duplicates and non-null priority duplicates are both
rejected with explicit 400 codes; unknown (non-catalog or non-UUID) course
ids are ACCEPTED (plan_items has no FK by schema) and surface on GET as
``course: null`` - the UI renders them as removable placeholder cards.

Primary invariant end-to-end: first plan auto-primary; setting primary unsets
others atomically; ``is_primary: false`` in PATCH is rejected
(``cannot_unset_primary`` - primary moves by promoting another plan only);
deleting the primary promotes the oldest remaining plan, so an account with
>= 1 plan ALWAYS has exactly one primary.
"""

import uuid
from datetime import datetime
from typing import Annotated, Final

from fastapi import APIRouter, Depends, status
from fastapi.exceptions import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.courses import CourseOut
from app.api.deps import get_current_student, get_session
from app.plans import store

router: Final = APIRouter()

_NAME_MAX: Final = 80
_ITEMS_MAX: Final = 100
_PRIORITY_MAX: Final = 20


# ---------- payload / response models ----------


class PlanCreate(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, max_length=_NAME_MAX)


class PlanPatch(BaseModel):
    """``is_primary`` is set-true-only: false -> explicit 400."""

    model_config = ConfigDict(frozen=True)

    name: str | None = Field(default=None, min_length=1, max_length=_NAME_MAX)
    is_primary: bool | None = None


class ItemIn(BaseModel):
    model_config = ConfigDict(frozen=True)

    course_id: str = Field(min_length=1, max_length=64)
    priority: int | None = Field(default=None, ge=1, le=_PRIORITY_MAX)


class ItemsReplace(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[ItemIn] = Field(max_length=_ITEMS_MAX)


class PlanOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    name: str
    is_primary: bool
    item_count: int
    created_at: datetime
    updated_at: datetime | None


class ItemOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    course_id: str
    priority: int | None
    added_at: datetime
    course: CourseOut | None


# ---------- shared dependencies / helpers ----------

CurrentStudent = Annotated[str, Depends(get_current_student)]
DbSession = Annotated[AsyncSession, Depends(get_session)]


async def _student_id(session: AsyncSession, student_no: str) -> uuid.UUID:
    """Site session -> persisted identity row (404 class: never reached after
    a login we recorded; if the row is gone the session is treated as dead)."""
    student_id = await store.resolve_student_id(session, student_no)
    if student_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="not_authenticated"
        )
    return student_id


async def _owned(session: AsyncSession, student_id: uuid.UUID, plan_id: uuid.UUID):
    plan = await store.get_owned_plan(session, student_id, plan_id)
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="plan_not_found")
    return plan


def _plan_out(plan, item_count: int) -> PlanOut:
    return PlanOut(
        id=plan.id,
        name=plan.name,
        is_primary=plan.is_primary,
        item_count=item_count,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )


async def _items_out(session: AsyncSession, items) -> list[ItemOut]:
    courses = await store.attach_courses(session, items)
    return [
        ItemOut(
            course_id=item.course_id,
            priority=item.priority,
            added_at=item.added_at,
            course=(
                CourseOut.from_course(courses[item.course_id])
                if item.course_id in courses
                else None
            ),
        )
        for item in items
    ]


# ---------- routes ----------


@router.get("/api/plans", response_model=list[PlanOut])
async def list_my_plans(student: CurrentStudent, db: DbSession) -> list[PlanOut]:
    student_id = await _student_id(db, student)
    rows = await store.list_plans(db, student_id)
    return [_plan_out(plan, count) for plan, count in rows]


@router.post("/api/plans", response_model=PlanOut, status_code=status.HTTP_201_CREATED)
async def create_plan(body: PlanCreate, student: CurrentStudent, db: DbSession) -> PlanOut:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="name_required")
    student_id = await _student_id(db, student)
    plan = await store.create_plan(db, student_id, name)
    return _plan_out(plan, 0)


@router.patch("/api/plans/{plan_id}", response_model=PlanOut)
async def patch_plan(
    plan_id: uuid.UUID, body: PlanPatch, student: CurrentStudent, db: DbSession
) -> PlanOut:
    if body.name is None and body.is_primary is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="empty_patch")
    student_id = await _student_id(db, student)
    plan = await _owned(db, student_id, plan_id)

    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="name_required"
            )
        await store.rename_plan(db, plan, name)
    if body.is_primary is True:
        await store.set_primary(db, student_id, plan)
    elif body.is_primary is False:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="cannot_unset_primary"
        )
    items = await store.list_items(db, plan.id)  # unaffected; count via same reader
    return _plan_out(plan, len(items))


@router.delete("/api/plans/{plan_id}")
async def delete_plan(plan_id: uuid.UUID, student: CurrentStudent, db: DbSession) -> dict:
    student_id = await _student_id(db, student)
    plan = await _owned(db, student_id, plan_id)
    promoted = await store.delete_plan(db, student_id, plan)
    return {
        "ok": True,
        "promoted_plan_id": str(promoted.id) if promoted is not None else None,
    }


@router.get("/api/plans/{plan_id}/items", response_model=list[ItemOut])
async def get_items(plan_id: uuid.UUID, student: CurrentStudent, db: DbSession):
    student_id = await _student_id(db, student)
    plan = await _owned(db, student_id, plan_id)
    return await _items_out(db, await store.list_items(db, plan.id))


@router.put("/api/plans/{plan_id}/items", response_model=list[ItemOut])
async def put_items(
    plan_id: uuid.UUID, body: ItemsReplace, student: CurrentStudent, db: DbSession
):
    student_id = await _student_id(db, student)
    plan = await _owned(db, student_id, plan_id)

    seen_courses: set[str] = set()
    seen_priorities: set[int] = set()
    for item in body.items:
        if item.course_id in seen_courses:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="duplicate_course_id"
            )
        seen_courses.add(item.course_id)
        if item.priority is not None:
            if item.priority in seen_priorities:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="duplicate_priority"
                )
            seen_priorities.add(item.priority)

    stored = await store.replace_items(
        db, plan, [(item.course_id, item.priority) for item in body.items]
    )
    return await _items_out(db, stored)
