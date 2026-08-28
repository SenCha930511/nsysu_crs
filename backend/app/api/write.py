"""POST /api/write/preview (plan todo 14): checks + replay payload preview +
single-use confirm_token. Every school call is FRESH (no caching between
previews): after the CSRF middleware (403) and site-session (401), we run
selcrs-jar check (401) -> school breaker gate (todo 17: open -> 503 LOCAL -
the write entrance is hard-off with zero school contact; coherent school
outcomes close the breaker, failures re-feed the streak) -> fresh Studfun
stage probe + form GET (409/503/401
routing) -> typed-400 shape checks -> app.write.preview per-op verdicts
(無課號/同批加退混雜/不在已選/衝堂, quota only as warnings) -> on full pass,
canonicalize (app.write.canonical, shared with todo 15) -> replay payload
over the scraped hidden inputs (Studfun params as fallback) ->
base64url(sha256(student_no|canonical_ops|APP_SECRET)) token into Redis
``confirm:{token}`` TTL 300s, single-use via GETDEL at confirm (todo 15:
replay -> 409).
"""

from typing import Annotated, Final

from fastapi import APIRouter, Depends, Request, status
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_student, get_redis, get_session
from app.api.write_probe import probe_stage
from app.auth.breaker import build_breaker
from app.auth.redis_iface import AuthRedis
from app.auth.sessions import SESSION_COOKIE_NAME, load_selcrs
from app.config import Settings
from app.selections.store import item_identity, load_snapshot
from app.stage.detect import VARIANT_SSFORM, VARIANT_STAGE5, is_writable
from app.write.canonical import (
    CanonicalOp,
    canonical_ops,
    canonical_segments,
    confirm_token,
    payload_hash,
)
from app.write.catalog import resolve_course, resolve_courses_by_ids
from app.write.confirm import ConfirmRecord, store_confirm
from app.write.payload import (
    SEND_NAME,
    build_payload_ssprs,
    build_payload_stage5,
    parse_form_hidden_inputs,
    parse_send_value,
)
from app.write.preview import ClashTarget, OpVerdict, ResolvedOp, evaluate_ops
from app.write.schemas import (
    OpIn,
    OpVerdictOut,
    PreviewRequest,
    PreviewResponse,
    QuotaOut,
)
from app.write.timetable import days_from_fused

router: Final = APIRouter()

ERR_EXPIRED: Final = "SELCRS_EXPIRED"
ERR_SCHOOL: Final = "school_unavailable"
ERR_STAGE: Final = "stage_unavailable"

MAX_OPS_BY_VARIANT: Final = {VARIANT_SSFORM: 15, VARIANT_STAGE5: 10}
_BUILDERS: Final = {VARIANT_SSFORM: build_payload_ssprs, VARIANT_STAGE5: build_payload_stage5}

WARN_QUOTA_SNAPSHOT: Final = "quota_snapshot"


def _session_id(request: Request) -> str:
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id is None:  # unreachable: the auth dependency ran first
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="not_authenticated"
        )
    return session_id


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _validate_ops(ops: list[OpIn], *, limit: int) -> None:
    """Request-shape checks (typed 400s; per-op state checks come later)."""
    seen_priorities: set[int] = set()
    for op in ops:
        if op.action == "+":
            if op.priority is None:
                raise _bad_request("priority_required")
            if not 1 <= op.priority <= 20:
                raise _bad_request("priority_invalid")
            if op.priority in seen_priorities:
                raise _bad_request("priority_duplicate")
            seen_priorities.add(op.priority)
        elif op.priority is not None:
            raise _bad_request("priority_forbidden")
    if len(ops) > limit:
        raise _bad_request("ops_limit_exceeded")


def _verdict_out(verdict: OpVerdict) -> OpVerdictOut:
    course = verdict.course
    quota = None
    if course.course_id is not None:
        quota = QuotaOut(
            restrict=course.restrict,
            select_n=course.select_n,
            selected_n=course.selected_n,
            remaining=course.remaining,
            ingested_at=course.ingested_at,
        )
    return OpVerdictOut(
        index=verdict.index,
        action=verdict.action,
        course_id=verdict.ident,
        code=verdict.code,
        writable=verdict.writable,
        verdict=verdict.verdict,
        detail=verdict.detail,
        warnings=list(verdict.warnings),
        quota=quota,
    )


async def _selection_targets(
    db: AsyncSession, *, year_sem: str, redis: AuthRedis, session_id: str
) -> tuple[list[ClashTarget], frozenset[str]]:
    """Latest synced selections as clash targets + the '-' membership set."""
    snapshot = await load_snapshot(redis, session_id)
    items = snapshot.items if snapshot is not None else []
    by_id = await resolve_courses_by_ids(
        db,
        year_sem=year_sem,
        course_ids=[item.course_id for item in items if item.course_id is not None],
    )
    targets: list[ClashTarget] = []
    for item in items:
        days = None
        if item.course_id is not None and item.course_id in by_id:
            days = by_id[item.course_id].class_time
        elif item.times is not None:
            days = days_from_fused(item.times)
        if days is None:
            continue
        targets.append(ClashTarget(label=item.code or item_identity(item), days=tuple(days)))
    selected_codes = frozenset(item.code for item in items if item.code is not None)
    return targets, selected_codes


@router.post("/api/write/preview", response_model=None)
async def post_write_preview(
    body: PreviewRequest,
    request: Request,
    student_no: Annotated[str, Depends(get_current_student)],
    redis: Annotated[AuthRedis, Depends(get_redis)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> PreviewResponse | JSONResponse:
    settings: Settings = request.app.state.settings
    session_id = _session_id(request)

    jar_payload = await load_selcrs(
        redis, session_id, sliding_ttl=settings.selcrs_session_ttl_sliding
    )
    if jar_payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=ERR_EXPIRED)

    breaker = build_breaker(redis, settings)
    if not await breaker.admit():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=ERR_SCHOOL
        )
    # Fresh stage probe (plan: preview never rides a cached stage). probe_stage
    # already mapped SelcrsUnavailable/Expired onto its 503/401 contract.
    try:
        probe = await probe_stage()
    except HTTPException as exc:
        if exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE and exc.detail == ERR_SCHOOL:
            await breaker.record_unknown()
        elif exc.status_code == status.HTTP_401_UNAUTHORIZED and exc.detail == ERR_EXPIRED:
            await breaker.record_classified()
        raise
    await breaker.record_classified()
    detection = probe.detection
    if not is_writable(
        detection,
        need_confirmation=probe.need_confirmation,
        first_round_write=settings.feature_first_round_write,
    ):
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "detail": ERR_STAGE,
                "stage": detection.stage,
                "reason": detection.reason,
                "need_confirmation": probe.need_confirmation,
            },
        )
    variant = detection.variant
    form_html = probe.form_html
    form_url = probe.form_url
    if variant is None or form_html is None or form_url is None:
        # parse_studfun contract: writable implies a matched form link; a
        # breach is detector drift -> unrecognized school behaviour, 503.
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=ERR_SCHOOL)

    _validate_ops(body.ops, limit=MAX_OPS_BY_VARIANT[variant])

    resolved: list[ResolvedOp] = []
    for index, op_in in enumerate(body.ops):
        course = await resolve_course(
            db, year_sem=settings.semester_year_sem, ident=op_in.course_id
        )
        # Check 9 (typed confirmation) is only meaningful with a resolved
        # code; an unresolvable drop op already carries the 無課號 verdict.
        if op_in.action == "-" and course.code is not None and op_in.drop_confirm_text != course.code:
            raise _bad_request("typed_confirmation_missing")
        resolved.append(
            ResolvedOp(index, op_in.action, op_in.course_id, op_in.priority, course)
        )

    targets, selected_codes = await _selection_targets(
        db, year_sem=settings.semester_year_sem, redis=redis, session_id=session_id
    )
    verdicts = evaluate_ops(resolved, selected_codes=selected_codes, selection_targets=targets)

    quota_dates = sorted(
        {iso for verdict in verdicts if (iso := verdict.course.ingested_at) is not None}
    )
    base = {
        "stage": detection.stage,
        "variant": variant,
        "form_url": form_url,
        "ops": [_verdict_out(verdict) for verdict in verdicts],
        "warnings": [WARN_QUOTA_SNAPSHOT] if quota_dates else [],
        "quota_as_of": quota_dates[-1] if quota_dates else None,
    }
    if not all(verdict.writable for verdict in verdicts):
        return PreviewResponse(
            **base, writable=False, payload=None, confirm_token=None,
            payload_hash=None, canonical_ops=None,
        )

    canonical = canonical_ops(
        [
            CanonicalOp(
                action=verdict.action,
                code=verdict.code,
                priority=resolved[verdict.index].priority,
            )
            for verdict in verdicts
            if verdict.code is not None
        ]
    )
    # Replay assembly: scraped hidden inputs verbatim; Studfun params are
    # only the fallback for keys the form herself lacks (plan todo 14).
    hidden = parse_form_hidden_inputs(form_html)
    if detection.params is not None:
        for key, value in detection.params.model_dump().items():
            if value is not None:
                hidden.setdefault(key, value)
    send_value = parse_send_value(form_html)
    if send_value is not None:
        hidden.setdefault(SEND_NAME, send_value)
    payload = _BUILDERS[variant](canonical, hidden)

    segments = canonical_segments(canonical)
    token = confirm_token(student_no, canonical, secret=settings.app_secret)
    await store_confirm(
        redis,
        token,
        ConfirmRecord(
            student_no=student_no,
            canonical_ops=segments,
            variant=variant,
            form_url=form_url,
        ),
        ttl=settings.confirm_token_ttl,
    )
    return PreviewResponse(
        **base, writable=True, payload=payload, confirm_token=token,
        payload_hash=payload_hash(student_no, canonical), canonical_ops=segments,
    )
