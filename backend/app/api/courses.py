"""GET /api/courses - course catalog query endpoint (plan todo 7).

The handler is intentionally thin: parse -> 400 on CourseQueryError -> run the
two SELECTs -> serialize. All filter/SQL logic lives in app.catalog.query.

GET /api/courses/{course_id}/outline (2026-08-28 syllabus feature): per-click
public outline scrape, 30-minute Redis-cached, failures stay honest (404 when
the row has no outline URL, 502/503 on school-side trouble). Cross-school /
NODATA pages parse sparse but still return — the UI falls back to the source
link, which also rides the payload.
"""

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated, Final

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from redis.exceptions import RedisError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_redis, get_session
from app.auth.redis_iface import AuthRedis
from app.catalog.outline import OutlineData, parse_outline
from app.catalog.query import (
    PER_PAGE,
    CourseQueryError,
    fetch_page,
    parse_course_params,
    resolve_year_sem,
)
from app.config import Settings
from app.models.courses import Course
from app.selcrs.decode import decode_body
from app.selcrs.errors import SelcrsUnavailable
from app.selcrs.http import build_client, request_school

router: Final = APIRouter()

_OUTLINE_CACHE_TTL: Final = 1800  # seconds; outline pages change rarely.


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


class OutlineOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    name_zh: str | None = None
    code: str | None = None
    name_en: str | None = None
    course_type: str | None = None
    requirement: str | None = None
    dept: str | None = None
    instructor: str | None = None
    credit: str | None = None
    semester_title: str | None = None
    syllabus: str | None = None
    objectives: str | None = None
    teaching_methods: str | None = None
    evaluation: str | None = None
    references: str | None = None
    source_url: str
    fetched_at: str


def _outline_payload(
    data: OutlineData, *, source_url: str, fetched_at: str
) -> dict[str, object]:
    return OutlineOut(
        **{
            key: getattr(data, key)
            for key in (
                "name_zh",
                "code",
                "name_en",
                "course_type",
                "requirement",
                "dept",
                "instructor",
                "credit",
                "semester_title",
                "syllabus",
                "objectives",
                "teaching_methods",
                "evaluation",
                "references",
            )
        },
        source_url=source_url,
        fetched_at=fetched_at,
    ).model_dump()


@router.get("/api/courses/{course_id}/outline", response_model=None)
async def get_course_outline(
    course_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[AuthRedis, Depends(get_redis)],
) -> JSONResponse:
    url = (
        await db.execute(select(Course.url).where(Course.id == course_id))
    ).scalar_one_or_none()
    if url is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="course_not_found"
        )
    if url == "":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="outline_unavailable"
        )

    cache_key = f"crs:outline:{course_id}"
    cached = await redis.get(cache_key)
    if cached is not None:
        return JSONResponse(status_code=status.HTTP_200_OK, content=json.loads(cached))

    async with build_client() as client:
        try:
            resp = await request_school(client, "GET", url)
        except SelcrsUnavailable as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="school_unavailable",
            ) from exc
    if resp.status_code != status.HTTP_200_OK:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="school_outline_error",
        )
    data = parse_outline(decode_body(resp.content, resp.headers.get("content-type")))
    fetched_at = datetime.now(UTC).isoformat()
    payload = _outline_payload(data, source_url=url, fetched_at=fetched_at)
    try:
        await redis.set(
            cache_key, json.dumps(payload, ensure_ascii=False), ex=_OUTLINE_CACHE_TTL
        )
    except RedisError as exc:  # cache is an optimization, not a failure mode
        logging.getLogger(__name__).warning(
            "outline cache write skipped (redis unavailable): %s", exc
        )
    return JSONResponse(status_code=status.HTTP_200_OK, content=payload)
