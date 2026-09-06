"""GET /api/me/payment-status + GET /api/me/enrollment-cert (stu-enroll §5.5).

Both endpoints are flag-gated (FEATURE_STU_ENROLL; off -> 404, the README's
non-public-endpoint rule) and session-gated (get_current_student). The
school-side contract mirrors selections.py: regweb jar gone -> 401
REGWEB_EXPIRED; open breaker -> 503 LOCALLY with zero school contact; relay
bounce -> 401 REGWEB_EXPIRED (+ record_classified); unrecognized school
behaviour -> 503 school_unavailable (+ record_unknown); coherent outcomes
close/reset the breaker. The cert PDF is pure passthrough: it never enters
any cache, DB, or log - response no-store + attachment (plan §5.6). Neither
the jar nor any cookie value ever enters a response body, log line, or DB.
"""

from datetime import datetime
from typing import Annotated, Final
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.exceptions import HTTPException
from pydantic import BaseModel, ConfigDict

from app.api.deps import get_current_student, get_redis
from app.auth.breaker import build_breaker
from app.auth.redis_iface import AuthRedis
from app.auth.sessions import SESSION_COOKIE_NAME, load_regweb, load_stusco
from app.config import Settings
from app.selcrs.decode import decode_body
from app.selcrs.errors import SelcrsSessionExpired, SelcrsUnavailable
from app.selcrs.jar import deserialize_cookies
from app.stuenroll.endpoints import (
    CHECKLIST_RELAY_URL,
    ENROLLCERT_RELAY_URL,
    RECEIPT_RELAY_PREFIX,
    SCO_HISTORY_URL,
    TFSTU_RELAY_URL,
)
from app.stuenroll.parse import (
    parse_grades_history,
    parse_payment_bills,
    parse_regweb_checklist,
)
from app.stuenroll.relay import open_relay
from app.stuenroll.store import (
    GradesSnapshot,
    diff_grade_rows,
    load_grades_snapshot,
    store_grades_snapshot,
)

router: Final = APIRouter()

ERR_REGWEB_EXPIRED: Final = "REGWEB_EXPIRED"
ERR_SCO_EXPIRED: Final = "SCO_EXPIRED"
ERR_SCHOOL: Final = "school_unavailable"


class PaymentBillItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    item: str
    amount: str
    status: str
    pay_date: str
    receipt_available: bool


class PaymentStatusResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    dept: str
    bills: list[PaymentBillItem]


def _session_id(request: Request) -> str:
    """Site session id from the cookie (get_current_student already resolved it)."""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id is None:  # unreachable: the auth dependency ran first
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="not_authenticated"
        )
    return session_id


def _now_iso(settings: Settings) -> str:
    return datetime.now(ZoneInfo(settings.tz)).isoformat(timespec="seconds")


def _require_feature(settings: Settings) -> None:
    if not settings.feature_stu_enroll:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")


async def _load_regweb_payload(request: Request, redis: AuthRedis) -> str:
    settings: Settings = request.app.state.settings
    payload = await load_regweb(
        redis, _session_id(request), sliding_ttl=settings.selcrs_session_ttl_sliding
    )
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=ERR_REGWEB_EXPIRED)
    return payload


@router.get("/api/me/payment-status", response_model=PaymentStatusResponse)
async def get_payment_status(
    request: Request,
    _student: Annotated[str, Depends(get_current_student)],
    redis: Annotated[AuthRedis, Depends(get_redis)],
) -> PaymentStatusResponse:
    """tfstudata bill rows, live per request (plan §5.5 allows either caching
    or live; live keeps the first version free of stale-balance surprises)."""
    settings: Settings = request.app.state.settings
    _require_feature(settings)
    payload = await _load_regweb_payload(request, redis)
    breaker = build_breaker(redis, settings)
    if not await breaker.admit():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=ERR_SCHOOL
        )
    try:
        landing = await open_relay(TFSTU_RELAY_URL, deserialize_cookies(payload))
        page = parse_payment_bills(decode_body(landing.content, landing.content_type))
    except SelcrsSessionExpired:
        await breaker.record_classified()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=ERR_REGWEB_EXPIRED
        ) from None
    except SelcrsUnavailable as exc:
        await breaker.record_unknown()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=ERR_SCHOOL
        ) from exc
    await breaker.record_classified()
    return PaymentStatusResponse(
        dept=page.dept,
        bills=[
            PaymentBillItem(
                item=bill.item,
                amount=bill.amount,
                status=bill.status,
                pay_date=bill.pay_date,
                receipt_available=bill.receipt_href is not None,
            )
            for bill in page.bills
        ],
    )


@router.get("/api/me/enrollment-cert")
async def get_enrollment_cert(
    request: Request,
    _student: Annotated[str, Depends(get_current_student)],
    redis: Annotated[AuthRedis, Depends(get_redis)],
) -> Response:
    """產生在學證明 PDF passthrough: relay chain to print/enrollcert.asp,
    streamed straight back with no-store. Landing must BE a pdf - anything
    else is shape drift, not an empty cert."""
    settings: Settings = request.app.state.settings
    _require_feature(settings)
    payload = await _load_regweb_payload(request, redis)
    breaker = build_breaker(redis, settings)
    if not await breaker.admit():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=ERR_SCHOOL
        )
    try:
        landing = await open_relay(ENROLLCERT_RELAY_URL, deserialize_cookies(payload))
        content_type = (landing.content_type or "").lower()
        if "pdf" not in content_type and not landing.content.startswith(b"%PDF"):
            raise SelcrsUnavailable("enrollcert relay did not land on a PDF")
    except SelcrsSessionExpired:
        await breaker.record_classified()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=ERR_REGWEB_EXPIRED
        ) from None
    except SelcrsUnavailable as exc:
        await breaker.record_unknown()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=ERR_SCHOOL
        ) from exc
    await breaker.record_classified()
    return Response(
        content=landing.content,
        media_type="application/pdf",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": 'attachment; filename="enrollment_cert.pdf"',
        },
    )


class GradesResponse(BaseModel):
    """GET shape: last sync + verbatim row cells; empty (null time) pre-sync."""

    model_config = ConfigDict(frozen=True)

    synced_at: str | None
    items: list[list[str]]


class GradesSyncResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    synced_at: str
    added: list[list[str]]
    removed: list[list[str]]
    unchanged: list[list[str]]
    items: list[list[str]]


@router.get("/api/me/grades", response_model=GradesResponse)
async def get_grades(
    request: Request,
    _student: Annotated[str, Depends(get_current_student)],
    redis: Annotated[AuthRedis, Depends(get_redis)],
) -> GradesResponse:
    """The cached grades snapshot only - school contact happens on /sync."""
    settings: Settings = request.app.state.settings
    _require_feature(settings)
    snapshot = await load_grades_snapshot(redis, _session_id(request))
    if snapshot is None:
        return GradesResponse(synced_at=None, items=[])
    return GradesResponse(synced_at=snapshot.synced_at, items=snapshot.items)


@router.post("/api/me/grades/sync", response_model=GradesSyncResponse)
async def post_grades_sync(
    request: Request,
    _student: Annotated[str, Depends(get_current_student)],
    redis: Annotated[AuthRedis, Depends(get_redis)],
) -> GradesSyncResponse:
    """Mirror of the selections sync contract, on the sco jar family: session,
    stusco jar (gone -> 401 SCO_EXPIRED), breaker gate (open -> 503 locally),
    one relay to the action=811 history page, bounce -> 401, drift -> 503,
    then identity diff and session-scoped snapshot replace (7d TTL)."""
    settings: Settings = request.app.state.settings
    _require_feature(settings)
    session_id = _session_id(request)
    payload = await load_stusco(
        redis, session_id, sliding_ttl=settings.selcrs_session_ttl_sliding
    )
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=ERR_SCO_EXPIRED)
    breaker = build_breaker(redis, settings)
    if not await breaker.admit():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=ERR_SCHOOL
        )
    try:
        landing = await open_relay(SCO_HISTORY_URL, deserialize_cookies(payload))
        page = parse_grades_history(decode_body(landing.content, landing.content_type))
    except SelcrsSessionExpired:
        await breaker.record_classified()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=ERR_SCO_EXPIRED
        ) from None
    except SelcrsUnavailable as exc:
        await breaker.record_unknown()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=ERR_SCHOOL
        ) from exc
    await breaker.record_classified()

    rows = [list(row) for row in page.rows]
    previous = await load_grades_snapshot(redis, session_id)
    added, removed, unchanged = diff_grade_rows(previous.items if previous else [], rows)
    synced_at = _now_iso(settings)
    await store_grades_snapshot(
        redis, session_id, GradesSnapshot(synced_at=synced_at, items=rows)
    )
    return GradesSyncResponse(
        synced_at=synced_at, added=added, removed=removed, unchanged=unchanged, items=rows
    )


class ChecklistItemOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str
    period: str
    status_text: str
    out_url: str | None = None


class ChecklistResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[ChecklistItemOut]
    enrollcert_present: bool


@router.get("/api/me/registration-checklist", response_model=ChecklistResponse)
async def get_registration_checklist(
    request: Request,
    _student: Annotated[str, Depends(get_current_student)],
    redis: Annotated[AuthRedis, Depends(get_redis)],
) -> ChecklistResponse:
    """WRegMain3 act=11 registration checklist rows, live per request (same
    freshness rationale as the payment bills)."""
    settings: Settings = request.app.state.settings
    _require_feature(settings)
    payload = await _load_regweb_payload(request, redis)
    breaker = build_breaker(redis, settings)
    if not await breaker.admit():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=ERR_SCHOOL
        )
    try:
        landing = await open_relay(CHECKLIST_RELAY_URL, deserialize_cookies(payload))
        page = parse_regweb_checklist(decode_body(landing.content, landing.content_type))
    except SelcrsSessionExpired:
        await breaker.record_classified()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=ERR_REGWEB_EXPIRED
        ) from None
    except SelcrsUnavailable as exc:
        await breaker.record_unknown()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=ERR_SCHOOL
        ) from exc
    await breaker.record_classified()
    return ChecklistResponse(
        items=[
            ChecklistItemOut(
                title=item.title,
                period=item.period,
                status_text=item.status_text,
                out_url=item.out_url,
            )
            for item in page.items
        ],
        enrollcert_present=page.enrollcert_present,
    )


@router.get("/api/me/payment-receipt")
async def get_payment_receipt(
    request: Request,
    _student: Annotated[str, Depends(get_current_student)],
    redis: Annotated[AuthRedis, Depends(get_redis)],
) -> Response:
    """Newest tfstudata bill that carries a receipt link, streamed back as PDF
    with no-store (mirrors the enrollment-cert passthrough)."""
    settings: Settings = request.app.state.settings
    _require_feature(settings)
    payload = await _load_regweb_payload(request, redis)
    breaker = build_breaker(redis, settings)
    if not await breaker.admit():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=ERR_SCHOOL
        )
    try:
        landing = await open_relay(TFSTU_RELAY_URL, deserialize_cookies(payload))
        page = parse_payment_bills(decode_body(landing.content, landing.content_type))
        receipt_href = next(
            (bill.receipt_href for bill in page.bills if bill.receipt_href is not None),
            None,
        )
        if receipt_href is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="receipt_not_available"
            )
        receipt_landing = await open_relay(
            f"{RECEIPT_RELAY_PREFIX}{receipt_href.lstrip('/')}", deserialize_cookies(payload)
        )
        content_type = (receipt_landing.content_type or "").lower()
        if "pdf" not in content_type and not receipt_landing.content.startswith(b"%PDF"):
            raise SelcrsUnavailable("receipt relay did not land on a PDF")
    except SelcrsSessionExpired:
        await breaker.record_classified()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=ERR_REGWEB_EXPIRED
        ) from None
    except SelcrsUnavailable as exc:
        await breaker.record_unknown()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=ERR_SCHOOL
        ) from exc
    await breaker.record_classified()
    return Response(
        content=receipt_landing.content,
        media_type="application/pdf",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": 'attachment; filename="payment_receipt.pdf"',
        },
    )
