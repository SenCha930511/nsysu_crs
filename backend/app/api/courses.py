"""GET /api/courses - course catalog query endpoint (plan todo 7).

The handler is intentionally thin: parse -> 400 on CourseQueryError -> run the
two SELECTs -> serialize. All filter/SQL logic lives in app.catalog.query.
"""

import uuid
from datetime import datetime
from typing import Final

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.catalog.query import (
    PER_PAGE,
    CourseQueryError,
    fetch_page,
    parse_course_params,
    resolve_year_sem,
)
from app.config import Settings
from app.models.courses import Course

router: Final = APIRouter()


class CourseOut(BaseModel):
    """One courses row as served to the frontend.

    ``class_`` mirrors the ORM attribute (the SQL column is named ``class``);
    class_time serializes as the stored 7-element Monday..Sunday array.
    """

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    year_sem: str
    code: str | None
    dept: str | None
    grade: str | None
    class_: str | None
    name_zh: str | None
    name_en: str | None
    credit: int | None
    compulsory: bool
    restrict: int | None
    select_n: int | None
    selected_n: int | None
    remaining: int | None
    teacher: str | None
    room: str | None
    class_time: list[str] | None
    description: str | None
    tags: list[str] | None
    english: bool
    change: str | None
    change_desc: str | None
    url: str | None
    ingested_at: datetime

    @classmethod
    def from_course(cls, course: Course) -> "CourseOut":
        return cls(
            id=course.id,
            year_sem=course.year_sem,
            code=course.code,
            dept=course.dept,
            grade=course.grade,
            class_=course.class_,
            name_zh=course.name_zh,
            name_en=course.name_en,
            credit=course.credit,
            compulsory=course.compulsory,
            restrict=course.restrict,
            select_n=course.select_n,
            selected_n=course.selected_n,
            remaining=course.remaining,
            teacher=course.teacher,
            room=course.room,
            class_time=list(course.class_time) if course.class_time is not None else None,
            description=course.description,
            tags=list(course.tags) if course.tags is not None else None,
            english=course.english,
            change=course.change,
            change_desc=course.change_desc,
            url=course.url,
            ingested_at=course.ingested_at,
        )


class CoursePage(BaseModel):
    """Paged /api/courses payload (plan todo 7 response shape)."""

    model_config = ConfigDict(frozen=True)

    page: int
    per_page: int
    total: int
    items: list[CourseOut]


@router.get("/api/courses", response_model=CoursePage)
async def list_courses(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> CoursePage:
    settings: Settings = request.app.state.settings
    catalog_max = (
        await session.execute(select(func.max(Course.year_sem)))
    ).scalar_one()
    default_sem = resolve_year_sem(catalog_max, settings.semester_year_sem)
    try:
        filt = parse_course_params(request.query_params, default_year_sem=default_sem)
    except CourseQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    rows, total = await fetch_page(session, filt)
    return CoursePage(
        page=filt.page,
        per_page=PER_PAGE,
        total=total,
        items=[CourseOut.from_course(row) for row in rows],
    )
