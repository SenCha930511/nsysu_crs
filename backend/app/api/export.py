"""POST /api/plans/export.ics - serialize course ids into an RFC5545 .ics.

Anonymous by design: the payload carries ids of PUBLIC catalog rows the caller
already sees in their timetable (guest staging or catalog-joined selections),
and the output is deterministic for identical inputs (build_plan_ics contract).
"""

import uuid
from typing import Final

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.exceptions import HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.config import Settings
from app.export.ics import IcsBuildError, build_plan_ics
from app.models.courses import Course

router: Final = APIRouter()

ERR_NOT_FOUND: Final = "course_not_found"
ERR_EMPTY: Final = "plan_empty"
ERR_BUILD: Final = "plan_invalid"

MAX_PLAN_COURSES: Final = 30


class ExportIcsRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    plan_name: str | None = None
    course_ids: list[uuid.UUID]


@router.post("/api/plans/export.ics")
async def export_plan_ics(
    request: Request,
    body: ExportIcsRequest,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Resolve the requested catalog rows, serialize, stream the .ics back."""
    settings: Settings = request.app.state.settings
    if len(body.course_ids) > MAX_PLAN_COURSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=ERR_BUILD
        )
    if not body.course_ids:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ERR_EMPTY)

    rows = list(
        (
            await session.execute(select(Course).where(Course.id.in_(body.course_ids)))
        )
        .scalars()
        .all()
    )
    by_id = {course.id: course for course in rows}
    missing = [str(cid) for cid in body.course_ids if cid not in by_id]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{ERR_NOT_FOUND}: {', '.join(missing)}",
        )
    courses = [by_id[cid] for cid in body.course_ids]

    try:
        built = build_plan_ics(body.plan_name or "", courses, settings)
    except IcsBuildError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"{ERR_BUILD}: {exc.args[0]}"
        ) from exc
    if built.event_count == 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ERR_EMPTY)

    return Response(
        content=built.content,
        media_type="text/calendar",
        headers={"Content-Disposition": 'attachment; filename="timetable.ics"'},
    )
