"""POST /api/write/submit (plan todo 15): confirm -> re-auth -> enqueue.

Order (each stage is local/atomic before the next touches anything):

1. CSRF middleware (403) + site session (401) run before this handler.
2. Atomic GETDEL of ``confirm:{token}`` (single-use): unknown token or a
   replay -> flat 409, no school contact, nothing enqueued.
3. Ownership: the record's student_no must match the session's (a token is
   unforgeable - the preimage carries the APP_SECRET - but a LEAKED token
   must still not cross students).
4. Re-verify the password against SSO2 RIGHT NOW (plan: 寫入當下重打密碼).
   CREDENTIAL-FAIL -> 401 and NOTHING is enqueued; UNKNOWN -> 503 + breaker,
   never an account signal (same routing as /api/auth/login).
5. The fresh SSO2 jar overwrites the session's selcrs jar in Redis (the
   queued job runs against THIS jar); Redis-only, never Postgres.
6. Canonicalize + payload_hash; the partial unique index makes the enqueue
   atomic: a duplicate active payload_hash -> 409 carrying the existing job
   id (fast-path read first, IntegrityError as the race backstop).
7. Job row commits BEFORE the Redis RPUSH: a popped ticket always finds its
   ledger row. A Redis failure after commit surfaces as 503; the orphaned
   queued job is dwell-cancelled honestly at WRITE_QUEUE_DWELL_MAX.
"""

from typing import Annotated, Final

from fastapi import APIRouter, Depends, Request, status
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_student, get_redis, get_session
from app.auth.breaker import build_breaker
from app.auth.redis_iface import AuthRedis
from app.auth.sessions import SESSION_COOKIE_NAME, store_selcrs
from app.config import Settings
from app.selcrs.endpoints import Sso2Result, login_sso2
from app.selcrs.errors import SelcrsUnavailable
from app.selcrs.jar import serialize_cookies
from app.selcrs.sso2 import Sso2Outcome
from app.write import jobs
from app.write.canonical import parse_canonical_segments, payload_hash
from app.write.confirm import consume_confirm
from app.write.queue import QueueTicket, enqueue_ticket

router: Final = APIRouter()

_ERR_UNKNOWN_TOKEN: Final = "confirm_token_unknown"
_ERR_DUPLICATE: Final = "duplicate_active_job"
_ERR_SCHOOL: Final = "school_unavailable"


class SubmitRequest(BaseModel):
    """Confirm body; password lives as a SecretStr until the SSO2 call."""

    model_config = ConfigDict(frozen=True)

    confirm_token: str | None = Field(default=None, max_length=128)
    password: SecretStr = Field(min_length=1, max_length=128)


class SubmitResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    job_id: str
    status: str
    payload_hash: str


def _error(status_code: int, detail: str, **extra: object) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": detail, **extra})


@router.post("/api/write/submit", response_model=None)
async def post_write_submit(
    body: SubmitRequest,
    request: Request,
    student_no: Annotated[str, Depends(get_current_student)],
    redis: Annotated[AuthRedis, Depends(get_redis)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> SubmitResponse | JSONResponse:
    settings: Settings = request.app.state.settings
    if not body.confirm_token:  # "無 token 直打 submit 400" (plan todo 14)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="confirm_token_required"
        )
    record = await consume_confirm(redis, body.confirm_token)
    if record is None or record.student_no != student_no:
        return _error(status.HTTP_409_CONFLICT, _ERR_UNKNOWN_TOKEN)

    breaker = build_breaker(redis, settings)
    if not await breaker.admit():
        return _error(status.HTTP_503_SERVICE_UNAVAILABLE, _ERR_SCHOOL)
    try:
        result: Sso2Result = await login_sso2(
            student_no, body.password.get_secret_value()
        )
    except SelcrsUnavailable:
        # UNKNOWN school behaviour: breaker input, never an account signal.
        await breaker.record_unknown()
        return _error(status.HTTP_503_SERVICE_UNAVAILABLE, _ERR_SCHOOL)
    await breaker.record_classified()
    if result.outcome is Sso2Outcome.CREDENTIAL_FAIL:
        return _error(
            status.HTTP_401_UNAUTHORIZED, "invalid_credentials", school_msg=result.detail
        )

    # The fresh jar is the one the queued job will run against.
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id is None:  # unreachable: the auth dependency ran first
        return _error(status.HTTP_401_UNAUTHORIZED, "not_authenticated")
    await store_selcrs(
        redis,
        session_id,
        serialize_cookies(result.cookies),
        sliding_ttl=settings.selcrs_session_ttl_sliding,
        hard_ttl=settings.selcrs_session_ttl_hard,
    )

    try:
        ops = list(parse_canonical_segments(record.canonical_ops))
    except ValueError:  # a stored record that cannot re-derive ops is unusable
        return _error(status.HTTP_409_CONFLICT, _ERR_UNKNOWN_TOKEN)
    phash = payload_hash(student_no, ops)
    student_id = await jobs.find_student_id(db, student_no)
    if student_id is None:  # session predates the students row: refuse honestly
        return _error(status.HTTP_409_CONFLICT, "student_identity_missing")

    existing = await jobs.find_active_job_by_hash(db, phash)
    if existing is not None:
        return _error(status.HTTP_409_CONFLICT, _ERR_DUPLICATE, job_id=str(existing.id))
    try:
        job = await jobs.create_queued_job(
            db, student_id=student_id, ops=ops, payload_hash=phash
        )
        await db.commit()
    except jobs.DuplicateActiveJob:
        await db.rollback()
        raced = await jobs.find_active_job_by_hash(db, phash)
        if raced is None:  # the raced job finished between flush and re-read
            return _error(status.HTTP_409_CONFLICT, _ERR_DUPLICATE)
        return _error(status.HTTP_409_CONFLICT, _ERR_DUPLICATE, job_id=str(raced.id))

    await enqueue_ticket(
        redis,
        QueueTicket(
            job_id=str(job.id),
            session_ref=session_id,
            student_no=student_no,
            canonical_ops=record.canonical_ops,
            variant=record.variant,
            form_url=record.form_url,
        ),
    )
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=SubmitResponse(
            job_id=str(job.id), status="queued", payload_hash=phash
        ).model_dump(),
    )
