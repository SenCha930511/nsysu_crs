"""GET /api/write/jobs/{job_id} (plan todo 15): owner-only job view.

The view composes the durable ledger: job row (status + timestamps) joined
with the per-op write_audit outcomes keyed by (course, action). Distinct,
UI-facing messages for the two cancellation-family terminals - the plan
pins SESSION_SUPERSEDED its own copy ("你已在別處重新登入..."); the dwell
guard's cancellation is a different story ("排隊逾時"), and they must never
render as the same thing. A job containing unknown-reconciled ops carries
``reconcile=manual_resync_needed`` (worker could not auto-reconcile: session
dead/superseded or the reconcile query itself failed).
"""

import uuid
from typing import Annotated, Final

from fastapi import APIRouter, Depends, status
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_student, get_session
from app.write import jobs
from app.write.outcomes import OUTCOME_UNKNOWN_RECONCILED

router: Final = APIRouter()

_MSG_SUPERSEDED: Final = "你已在別處重新登入，此批送單已取消，請重新預檢"
_MSG_DWELL_CANCELLED: Final = "排隊逾時，此批送單已自動取消，請重新預檢"
_MSG_FAILED: Final = "送單未完成；各課結果如下，若為階段逾時請重新預檢"
_RECONCILE_MANUAL: Final = "manual_resync_needed"

_STATUS_MESSAGES: Final = {
    "session_superseded": _MSG_SUPERSEDED,
    "cancelled": _MSG_DWELL_CANCELLED,
    "failed": _MSG_FAILED,
}


class JobOpOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    action: str
    priority: int | None
    outcome: str | None
    school_msg: str | None


class JobView(BaseModel):
    model_config = ConfigDict(frozen=True)

    job_id: str
    status: str
    created_at: str
    started_at: str | None
    finished_at: str | None
    ops: list[JobOpOut]
    message: str | None
    reconcile: str | None


def _iso(moment: object) -> str:
    iso = getattr(moment, "isoformat", None)
    return iso() if callable(iso) else str(moment)


@router.get("/api/write/jobs/{job_id}", response_model=None)
async def get_write_job(
    job_id: str,
    student_no: Annotated[str, Depends(get_current_student)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> JobView | JSONResponse:
    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="job_not_found"
        ) from None
    student_id = await jobs.find_student_id(db, student_no)
    job = (
        await jobs.load_job_for_owner(db, job_uuid, student_id)
        if student_id is not None
        else None
    )
    if job is None:  # missing OR foreign job: the same flat 404 (no leak)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="job_not_found"
        )

    audits = await jobs.load_audits(db, job.id)
    by_pair: dict[tuple[str, str], tuple[str, str | None]] = {}
    for audit in audits:
        # Latest pending->outcome row wins per (course, action); rows are
        # ordered by created_at so a later write-back overwrites the pending.
        by_pair[(audit.course_id, audit.action)] = (audit.outcome, audit.school_msg)
    ops_out: list[JobOpOut] = []
    for op in job.ops:
        outcome, school_msg = by_pair.get(
            (str(op.get("code")), str(op.get("action"))), (None, None)
        )
        priority = op.get("priority")
        ops_out.append(
            JobOpOut(
                code=str(op.get("code")),
                action=str(op.get("action")),
                priority=priority if isinstance(priority, int) else None,
                outcome=outcome,
                school_msg=school_msg,
            )
        )
    reconcile = (
        _RECONCILE_MANUAL
        if any(op.outcome == OUTCOME_UNKNOWN_RECONCILED for op in ops_out)
        else None
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=JobView(
            job_id=str(job.id),
            status=job.status,
            created_at=_iso(job.created_at),
            started_at=_iso(job.started_at) if job.started_at is not None else None,
            finished_at=_iso(job.finished_at) if job.finished_at is not None else None,
            ops=ops_out,
            message=_STATUS_MESSAGES.get(job.status),
            reconcile=reconcile,
        ).model_dump(),
    )
