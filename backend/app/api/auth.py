"""POST /api/auth/login, /logout, GET /api/auth/me (plan todo 8).

Login pipeline order (each stage is local before the next touches anything):

1. IP limiter (fixed clock-hour): EVERY attempt counts, including later
   local rejections - plan pins locked-429s into the IP budget; counting all
   attempts is the same rule applied uniformly.
2. Breaker ``admit()``: open -> local 503, zero school contact, zero streak
   feedback; read-only site keeps working.
3. Account lock check: locked -> local 429 BEFORE the school call and the
   failure log is NOT appended (local rejections are not school verdicts).
4. The one school call (SSO2). UNKNOWN raises SelcrsUnavailable -> breaker
   streak +1 -> 503, never the account lock. Any classified answer (SUCCESS
   or CREDENTIAL-FAIL) closes/resets the breaker.
5. CREDENTIAL-FAIL -> append sliding failure log (may trigger the fixed
   15-min lock) -> 401 with the school's marker summary. The school's own
   message already makes no distinction between no-such-student and wrong
   password, and neither do we.
6. SUCCESS -> students upsert + write-job supersede (one transaction) ->
   site session cookie + selcrs jar into Redis (sliding/hard TTL pair).
   Success NEVER clears the failure log.

Hygiene: request bodies are never logged anywhere in the app (uvicorn's
access log carries method+path+status only); the password lives as a
``SecretStr`` and is unwrapped once, at the adapter call; neither it nor any
cookie value ever enters a response body, log line, or the DB.
"""

import asyncio
import logging
from typing import Final

from fastapi import APIRouter, Depends, Request, status
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.api.deps import get_current_student, get_redis
from app.auth.breaker import build_breaker
from app.auth.lockout import FailureLog, IpLimiter
from app.auth.redis_iface import AuthRedis
from app.auth.sessions import (
    SESSION_COOKIE_NAME,
    cookie_secure,
    create_site_session,
    delete_site_session,
    store_regweb,
    store_selcrs,
    store_stusco,
    subsystem_availability,
)
from app.auth.students import record_successful_login
from app.config import Settings
from app.selcrs.endpoints import Sso2Result, login_sso2
from app.selcrs.errors import SelcrsUnavailable
from app.selcrs.jar import serialize_cookies
from app.selcrs.sso2 import Sso2Outcome
from app.stuenroll.pipeline import LegError, fanout_subsystem_logins
from app.write.csrf import csrf_cookie_name, mint_csrf_token, set_csrf_cookie

router: Final = APIRouter()

_logger = logging.getLogger(__name__)

_ERR_TOO_MANY: Final = "too_many_attempts"
_ERR_SCHOOL: Final = "school_unavailable"

# Keepalive for in-flight background fan-outs (module scope: outlives any
# single request; tasks self-discard on completion).
_background_fanout: set[asyncio.Task[None]] = set()


async def _run_fanout_and_store(
    redis: AuthRedis,
    session_id: str,
    student_no: str,
    password: str,
    settings: Settings,
) -> None:
    """Background fan-out after a SUCCESSFUL site login (flag already gated).

    Runs both subsystem logins, parks any family jars, then feeds the breaker
    school verdicts ONLY: an available leg records classified, a
    SCHOOL_UNAVAILABLE leg records unknown, and our-side failures (captcha
    budget, deadline, app bug) record nothing - so this can neither clear nor
    poison a genuine failure streak. Moving this behind the login response is
    the login-latency fix: the site login no longer pays 2x captcha-OCR
    round-trips before the student reaches the page.
    """
    try:
        fanout = await fanout_subsystem_logins(student_no, password)
        if fanout.regweb.jar is not None:
            await store_regweb(
                redis,
                session_id,
                serialize_cookies(fanout.regweb.jar),
                sliding_ttl=settings.selcrs_session_ttl_sliding,
                hard_ttl=settings.selcrs_session_ttl_hard,
            )
        if fanout.sco.jar is not None:
            await store_stusco(
                redis,
                session_id,
                serialize_cookies(fanout.sco.jar),
                sliding_ttl=settings.selcrs_session_ttl_sliding,
                hard_ttl=settings.selcrs_session_ttl_hard,
            )
        breaker = build_breaker(redis, settings)
        for leg in (fanout.regweb, fanout.sco):
            if leg.available:
                await breaker.record_classified()
            elif leg.error is LegError.SCHOOL_UNAVAILABLE:
                await breaker.record_unknown()
    except Exception:
        _logger.exception(
            "stu_enroll background fan-out failed (fail-soft; family jars may be absent)"
        )


class LoginRequest(BaseModel):
    """Login body. ``password`` stays a SecretStr until the adapter unwraps it."""

    model_config = ConfigDict(frozen=True)

    student_no: str = Field(min_length=1, max_length=32)
    password: SecretStr = Field(min_length=1, max_length=128)


class MeResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    student_no: str
    regweb_available: bool
    sco_available: bool
    feature_stu_enroll: bool

def _client_ip(request: Request) -> str:
    """First X-Forwarded-For hop behind Caddy, else the direct peer."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", maxsplit=1)[0].strip()
    return request.client.host if request.client is not None else "unknown"


def _error(status_code: int, detail: str, **extra: object) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": detail, **extra})


@router.post("/api/auth/login")
async def post_login(
    body: LoginRequest,
    request: Request,
    redis: AuthRedis = Depends(get_redis),
) -> JSONResponse:
    settings: Settings = request.app.state.settings

    limiter = IpLimiter(redis, hourly_limit=settings.login_ip_hourly_limit)
    if not limiter.admits(await limiter.hit(_client_ip(request))):
        return _error(status.HTTP_429_TOO_MANY_REQUESTS, _ERR_TOO_MANY)

    breaker = build_breaker(redis, settings)
    if not await breaker.admit():
        return _error(status.HTTP_503_SERVICE_UNAVAILABLE, _ERR_SCHOOL)

    student_no = body.student_no.strip()
    if not student_no:
        return _error(status.HTTP_400_BAD_REQUEST, "student_no_required")
    failure_log = FailureLog(
        redis,
        fail_limit=settings.login_fail_limit,
        lock_minutes=settings.login_lock_minutes,
        tz_name=settings.tz,
    )
    if await failure_log.is_locked(student_no):
        # The login page (todo 11) shows the fixed lock window as the retry
        # hint; the IP-limiter 429 above has no per-user message.
        return _error(
            status.HTTP_429_TOO_MANY_REQUESTS,
            _ERR_TOO_MANY,
            retry_after_minutes=settings.login_lock_minutes,
        )

    try:
        result: Sso2Result = await login_sso2(
            student_no, body.password.get_secret_value()
        )
    except SelcrsUnavailable:
        # UNKNOWN school behaviour: breaker input, NEVER an account signal.
        await breaker.record_unknown()
        return _error(status.HTTP_503_SERVICE_UNAVAILABLE, _ERR_SCHOOL)

    await breaker.record_classified()

    if result.outcome is Sso2Outcome.CREDENTIAL_FAIL:
        await failure_log.record_credential_fail(student_no)
        return _error(
            status.HTTP_401_UNAUTHORIZED,
            "invalid_credentials",
            school_msg=result.detail,
        )

    await record_successful_login(request.app.state.session_factory, student_no)
    session_id = await create_site_session(redis, student_no)
    await store_selcrs(
        redis,
        session_id,
        serialize_cookies(result.cookies),
        sliding_ttl=settings.selcrs_session_ttl_sliding,
        hard_ttl=settings.selcrs_session_ttl_hard,
    )
    # stu_enroll fan-out (plan §5.2 方案 A fail-soft; flag-gated): the same
    # password window funds both subsystem logins. Never pre-gates on the
    # breaker - fail-soft must not block site login - and breaker input is
    # limited to school verdicts: ok -> classified, SCHOOL_UNAVAILABLE ->
    # unknown; our-side failures (captcha budget, deadline, app bug) record
    # nothing, so the fan-out can neither clear nor poison a real streak.
    # Flag semantics changed for latency: the fan-out is SCHEDULED (its own
    # internal budget + fail-soft semantics unchanged), so availability flags
    # read false for THIS response and flip once the background task lands the
    # jars - /api/auth/me derives them from jar presence, and the frontend
    # re-polls it while stu_enroll_pending is true.
    stu_enroll_pending = False
    if settings.feature_stu_enroll:
        task = asyncio.create_task(
            _run_fanout_and_store(
                redis,
                session_id,
                student_no,
                body.password.get_secret_value(),
                settings,
            )
        )
        _background_fanout.add(task)
        task.add_done_callback(_background_fanout.discard)
        stu_enroll_pending = True
    # CSRF (todo 14): fresh token every login (rotation); body echoes it
    # because the cookie itself is httpOnly and JS must echo it as
    # X-CSRF-Token on /api/write/* - a same-origin channel, never logged.
    csrf_token = mint_csrf_token()
    response = JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "student_no": student_no,
            "csrf_token": csrf_token,
            "regweb_available": False,
            "sco_available": False,
            "stu_enroll_pending": stu_enroll_pending,
        },
    )
    response.set_cookie(
        SESSION_COOKIE_NAME,
        session_id,
        path="/",
        secure=cookie_secure(request),
        httponly=True,
        samesite="lax",
    )
    set_csrf_cookie(
        response,
        session_id,
        csrf_token,
        ttl=settings.csrf_token_ttl,
        secure=cookie_secure(request),
    )
    return response


@router.post("/api/auth/logout")
async def post_logout(
    request: Request, redis: AuthRedis = Depends(get_redis)
) -> JSONResponse:
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id is not None:
        await delete_site_session(redis, session_id)
    response = JSONResponse(status_code=status.HTTP_200_OK, content={"ok": True})
    secure = cookie_secure(request)
    response.delete_cookie(
        SESSION_COOKIE_NAME, path="/", secure=secure, httponly=True, samesite="lax"
    )
    if session_id is not None:
        response.delete_cookie(
            csrf_cookie_name(session_id),
            path="/",
            secure=secure,
            httponly=True,
            samesite="lax",
        )
    return response


@router.get("/api/auth/me", response_model=MeResponse)
async def get_me(
    request: Request,
    student_no: str = Depends(get_current_student),
    redis: AuthRedis = Depends(get_redis),
) -> MeResponse:
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id is None:  # unreachable: the auth dependency ran first
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="not_authenticated"
        )
    regweb_available, sco_available = await subsystem_availability(redis, session_id)
    settings: Settings = request.app.state.settings
    return MeResponse(
        student_no=student_no,
        regweb_available=regweb_available,
        sco_available=sco_available,
        feature_stu_enroll=settings.feature_stu_enroll,
    )
