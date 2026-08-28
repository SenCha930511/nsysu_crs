"""GET /api/stage (plan todo 13): dynamic window discovery + prestep gate.

Flow (read-only — the only school traffic is GETs, never a POST):

1. Site session required (``get_current_student`` -> 401 not_authenticated);
   selcrs jar from Redis (sliding-TTL refreshed — this IS school activity).
   Jar gone -> 401 SELCRS_EXPIRED.
2. School breaker gate (todo 17 full-degraded posture): while the breaker is
   open this endpoint answers 503 LOCALLY — anything that needs the school is
   hard-off, while catalog/meta reads stay up.
3. One GET Studfun.asp, parsed by ``app.stage.detect`` into
   stage/variant/params/reason. A login-page bounce -> 401 SELCRS_EXPIRED;
   unrecognized transport/HTTP behaviour -> 503 school_unavailable AND feeds
   the breaker streak; any coherent outcome closes/resets it.
4. When the page is open (a write-form link exists), ONE more same-session
   GET of that form page feeds ``need_confirmation`` (必修課程確認 pre-step:
   blocked until the user completes the confirmation on the school site).

Drift safety: the parser raises ONLY for a dead session. Every other school
shape — including total rewrites — lands as ``stage=未知`` with a machine
``reason`` and HTTP 200; unknown NEVER maps to writable (only a matched
ssform link is writable, and 初選 additionally requires
``FEATURE_FIRST_ROUND_WRITE=true``). ``need_confirmation`` forces
``writable=false`` on any open stage.
"""

from datetime import datetime
from typing import Annotated, Final
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request, status
from fastapi.exceptions import HTTPException
from pydantic import BaseModel, ConfigDict

from app.api.deps import get_current_student, get_redis
from app.auth.breaker import build_breaker
from app.auth.redis_iface import AuthRedis
from app.auth.sessions import SESSION_COOKIE_NAME, load_selcrs
from app.config import Settings
from app.selcrs.endpoints import SELCRS_BASE_URL, get_studfun, get_write_form
from app.selcrs.errors import SelcrsSessionExpired, SelcrsUnavailable
from app.selcrs.jar import deserialize_cookies
from app.stage.detect import (
    StageParams,
    StudfunDetection,
    detect_need_confirmation,
    is_writable,
    parse_studfun,
)

router: Final = APIRouter()

ERR_EXPIRED: Final = "SELCRS_EXPIRED"
ERR_SCHOOL: Final = "school_unavailable"

_STUDFUN_URL: Final = f"{SELCRS_BASE_URL}/menu4/Studfun.asp"


class StageResponse(BaseModel):
    """The shipped /api/stage shape (writable/reason always present)."""

    model_config = ConfigDict(frozen=True)

    stage: str
    variant: str | None
    params: StageParams | None
    need_confirmation: bool
    writable: bool
    reason: str
    checked_at: str


def _session_id(request: Request) -> str:
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id is None:  # unreachable: the auth dependency ran first
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="not_authenticated"
        )
    return session_id


def _writable(
    detection: StudfunDetection, *, need_confirmation: bool, first_round_write: bool
) -> bool:
    # Shared policy: app.stage.detect.is_writable (todo 14 preview mirrors it).
    return is_writable(
        detection,
        need_confirmation=need_confirmation,
        first_round_write=first_round_write,
    )


@router.get("/api/stage", response_model=StageResponse)
async def get_api_stage(
    request: Request,
    _student: Annotated[str, Depends(get_current_student)],
    redis: Annotated[AuthRedis, Depends(get_redis)],
) -> StageResponse:
    settings: Settings = request.app.state.settings
    jar_payload = await load_selcrs(
        redis, _session_id(request), sliding_ttl=settings.selcrs_session_ttl_sliding
    )
    if jar_payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=ERR_EXPIRED)

    breaker = build_breaker(redis, settings)
    if not await breaker.admit():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=ERR_SCHOOL
        )
    try:
        cookies = deserialize_cookies(jar_payload)
        detection = parse_studfun(await get_studfun(cookies))
        need_confirmation = False
        if detection.form_href is not None:
            form_html = await get_write_form(cookies, urljoin(_STUDFUN_URL, detection.form_href))
            need_confirmation = detect_need_confirmation(form_html)
    except SelcrsSessionExpired:
        # A login-page bounce still proves the host speaks its protocol.
        await breaker.record_classified()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=ERR_EXPIRED
        ) from None
    except SelcrsUnavailable as exc:
        await breaker.record_unknown()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=ERR_SCHOOL
        ) from exc
    await breaker.record_classified()

    return StageResponse(
        stage=detection.stage,
        variant=detection.variant,
        params=detection.params,
        need_confirmation=need_confirmation,
        writable=_writable(
            detection,
            need_confirmation=need_confirmation,
            first_round_write=settings.feature_first_round_write,
        ),
        reason=detection.reason,
        checked_at=datetime.now(ZoneInfo(settings.tz)).isoformat(timespec="seconds"),
    )
