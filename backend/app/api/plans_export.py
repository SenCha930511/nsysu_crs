"""GET /api/plans/{plan_id}/export.ics - RFC5545 ICS export of one plan (todo 12).

Same session + ownership contract as the plans CRUD routes: no session ->
401 ``not_authenticated``; a foreign plan id is a flat 404 ``plan_not_found``.

Failure contract (friendly JSON, never an empty/corrupt file):

- ``plan_empty_no_events`` (409): the plan has no catalog-joined course with
  any period data (empty plan, or only unknown/placeholder ids).
- ``bad_period_code`` (409): a catalog row's class_time carries an unknown
  period code - loud failure (plan todo 12 bad-input), never a silent skip.
  The detail objects carry the offending course/day/slot for the UI.

Determinism: two GETs on identical data are byte-identical (stable UID +
DTSTAMP, school-code based identity, no wall-clock anywhere).
"""

import uuid
from typing import Annotated, Final
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_student, get_session
from app.config import Settings
from app.export.ics import IcsBuildError, build_plan_ics
from app.plans import store

router: Final = APIRouter()

CurrentStudent = Annotated[str, Depends(get_current_student)]
DbSession = Annotated[AsyncSession, Depends(get_session)]


def _content_disposition(plan_name: str) -> str:
    """attachment header: an ASCII-safe plain ``filename`` (HTTP headers are
    latin-1, CJK cannot ride there) plus RFC5987 ``filename*`` carrying the
    full UTF-8 plan name for every modern browser to save with."""
    cleaned = (
        plan_name.replace("\\", "_")
        .replace('"', "_")
        .replace("\r", " ")
        .replace("\n", " ")
        .strip()
    )
    full = f"nsysu-crs-{cleaned or 'plan'}.ics"
    ascii_fallback = "nsysu-crs-" + "".join(
        ch if ch.isascii() and (ch.isalnum() or ch in "-_.") else "_"
        for ch in cleaned
    ).strip("_") + ".ics"
    if ascii_fallback in ("nsysu-crs-.ics", "nsysu-crs_.ics"):
        ascii_fallback = "nsysu-crs-plan.ics"
    return (
        f'attachment; filename="{ascii_fallback}"; '
        f"filename*=UTF-8''{quote(full, safe='')}"
    )


@router.get("/api/plans/{plan_id}/export.ics")
async def export_plan_ics(
    plan_id: uuid.UUID, request: Request, student: CurrentStudent, db: DbSession
) -> Response:
    student_id = await store.resolve_student_id(db, student)
    if student_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="not_authenticated"
        )
    plan = await store.get_owned_plan(db, student_id, plan_id)
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="plan_not_found"
        )

    items = await store.list_items(db, plan.id)
    courses_by_id = await store.attach_courses(db, items)
    ordered_courses = [
        courses_by_id[item.course_id] for item in items if item.course_id in courses_by_id
    ]

    settings: Settings = request.app.state.settings
    try:
        built = build_plan_ics(plan.name, ordered_courses, settings)
    except IcsBuildError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "bad_period_code",
                "message": (
                    f"課程「{exc.course_label}」的時間資料含有不支援的節次代碼"
                    f"（週{exc.day_index + 1} {exc.slot!r}），無法匯出 ICS。"
                ),
                "course": exc.course_label,
                "day_index": exc.day_index,
                "slot": exc.slot,
            },
        ) from exc
    if built.event_count == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "plan_empty_no_events",
                "message": "此課表沒有可匯出的課程時間（尚無課程，或課程皆無上課時段資料）。",
            },
        )

    return Response(
        content=built.content,
        media_type="text/calendar",
        headers={"Content-Disposition": _content_disposition(plan.name)},
    )
