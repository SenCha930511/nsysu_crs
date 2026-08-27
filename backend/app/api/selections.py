"""POST /api/me/selections/sync + GET /api/me/selections (plan todo 9).

Sync pipeline (each stage fails closed, previous snapshot never overwritten
on failure):

1. Site session required (``get_current_student`` -> 401 not_authenticated).
2. selcrs jar from Redis (``load_selcrs`` refreshes the school jar's sliding
   TTL - this sync IS school activity). Jar gone -> 401 SELCRS_EXPIRED.
3. One school GET slt_result.asp. A login-page bounce -> 401 SELCRS_EXPIRED;
   unrecognized/unreachable school behaviour -> 503 school_unavailable
   (SelcrsUnavailable; never a per-account signal).
4. Parse (real 14/13-col layouts) -> join courses by code (unmatched rows
   stay, ``unknown=true``) -> identity diff vs the previous snapshot ->
   replace the session-scoped Redis snapshot.

The snapshot is Redis-only (``selections:{session_id}``, 7d TTL): no Postgres
persistence for the selections list; purge on logout/TTL. Neither the jar nor
any cookie value ever enters a response body, log line, or the DB.
"""

from datetime import datetime
from typing import Annotated, Final
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request, status
from fastapi.exceptions import HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_student, get_redis, get_session
from app.auth.redis_iface import AuthRedis
from app.auth.sessions import SESSION_COOKIE_NAME, load_selcrs
from app.config import Settings
from app.selections.join import attach_course_matches
from app.selections.parse import SelectionItem, parse_slt_result
from app.selections.store import (
    SelectionsSnapshot,
    diff_items,
    load_snapshot,
    store_snapshot,
)
from app.selcrs.endpoints import get_slt_result
from app.selcrs.errors import SelcrsSessionExpired, SelcrsUnavailable
from app.selcrs.jar import deserialize_cookies

router: Final = APIRouter()

ERR_EXPIRED: Final = "SELCRS_EXPIRED"
ERR_SCHOOL: Final = "school_unavailable"


class SyncResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    synced_at: str
    added: list[SelectionItem]
    removed: list[SelectionItem]
    unchanged: list[SelectionItem]
    items: list[SelectionItem]


class SelectionsResponse(BaseModel):
    """GET shape: last sync + items; empty (null time, no items) pre-sync."""

    model_config = ConfigDict(frozen=True)

    synced_at: str | None
    items: list[SelectionItem]


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


@router.post("/api/me/selections/sync", response_model=SyncResponse)
async def post_selections_sync(
    request: Request,
    _student: Annotated[str, Depends(get_current_student)],
    redis: Annotated[AuthRedis, Depends(get_redis)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> SyncResponse:
    settings: Settings = request.app.state.settings
    session_id = _session_id(request)

    jar_payload = await load_selcrs(
        redis, session_id, sliding_ttl=settings.selcrs_session_ttl_sliding
    )
    if jar_payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=ERR_EXPIRED)

    try:
        html = await get_slt_result(deserialize_cookies(jar_payload))
        items = parse_slt_result(html)
    except SelcrsSessionExpired:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=ERR_EXPIRED
        ) from None
    except SelcrsUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=ERR_SCHOOL
        ) from exc

    items = await attach_course_matches(
        db, year_sem=settings.semester_year_sem, items=items
    )
    previous = await load_snapshot(redis, session_id)
    added, removed, unchanged = diff_items(previous.items if previous else [], items)
    synced_at = _now_iso(settings)
    await store_snapshot(
        redis, session_id, SelectionsSnapshot(synced_at=synced_at, items=items)
    )
    return SyncResponse(
        synced_at=synced_at, added=added, removed=removed, unchanged=unchanged, items=items
    )


@router.get("/api/me/selections", response_model=SelectionsResponse)
async def get_selections(
    request: Request,
    _student: Annotated[str, Depends(get_current_student)],
    redis: Annotated[AuthRedis, Depends(get_redis)],
) -> SelectionsResponse:
    snapshot = await load_snapshot(redis, _session_id(request))
    if snapshot is None:
        return SelectionsResponse(synced_at=None, items=[])
    return SelectionsResponse(synced_at=snapshot.synced_at, items=snapshot.items)
