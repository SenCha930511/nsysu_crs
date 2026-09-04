"""GET /api/schedule - the school's 選課日程 as anonymous JSON.

Informational widget data, so the contract mirrors /api/catalog/meta:
ALWAYS 200. ``ok`` is false only when no snapshot exists yet AND the live
fetch failed (school down, breaker open, or shape drift) - the frontend
then hides the widget instead of showing red. ``stale`` marks a last-good
snapshot served past its freshness window after a failed refresh.

School-touch policy (same as every other adapter call): a refresh runs
only behind the breaker; success/parse answers record_classified,
transport/drift failures record_unknown. Cached reads never touch the
school at all.
"""

from datetime import datetime
from typing import Annotated, Final, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from app.api.deps import get_redis
from app.auth.breaker import build_breaker
from app.auth.redis_iface import AuthRedis
from app.config import Settings
from app.schedule.front import FrontSchedule, parse_front_schedule
from app.schedule.store import (
    FRESHNESS_SECONDS,
    acquire_refresh_lock,
    load_cached,
    release_refresh_lock,
    save_cached,
)
from app.selcrs.endpoints import fetch_front_page
from app.selcrs.errors import SelcrsUnavailable

router: Final = APIRouter()


class ScheduleEventOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    label: str  # verbatim school wording
    kind: Literal["window", "instant"]
    start: datetime
    end: datetime | None


class ScheduleResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    ok: bool
    stale: bool
    fetched_at: datetime | None
    title: str | None
    events: list[ScheduleEventOut]


def _to_response(schedule: FrontSchedule, *, fetched_at: datetime) -> dict[str, object]:
    return {
        "fetched_at": fetched_at.isoformat(),
        "title": schedule.title,
        "events": [
            {
                "key": event.key,
                "label": event.label,
                "kind": event.kind,
                "start": event.start.isoformat(),
                "end": event.end.isoformat() if event.end is not None else None,
            }
            for event in schedule.events
        ],
    }


def _age_seconds(cached: dict[str, object], now: datetime) -> float | None:
    fetched_at = cached.get("fetched_at")
    if not isinstance(fetched_at, str):
        return None
    try:
        parsed = datetime.fromisoformat(fetched_at)
    except ValueError:
        return None
    return (now - parsed).total_seconds()


def _serve(
    cached: dict[str, object] | None, *, stale: bool
) -> ScheduleResponse:
    if cached is None:
        return ScheduleResponse(ok=False, stale=False, fetched_at=None, title=None, events=[])
    fetched_raw = cached.get("fetched_at")
    title_raw = cached.get("title")
    events_raw = cached.get("events", [])
    return ScheduleResponse(
        ok=True,
        stale=stale,
        fetched_at=datetime.fromisoformat(fetched_raw) if isinstance(fetched_raw, str) else None,
        title=title_raw if isinstance(title_raw, str) else None,
        events=[  # cached blobs were written by _to_response; validate per-field at the model
            ScheduleEventOut.model_validate(event)
            for event in (events_raw if isinstance(events_raw, list) else [])
            if isinstance(event, dict)
        ],
    )


@router.get("/api/schedule", response_model=ScheduleResponse)
async def get_schedule(
    request: Request,
    redis: Annotated[AuthRedis, Depends(get_redis)],
) -> ScheduleResponse:
    settings: Settings = request.app.state.settings
    now = datetime.now(ZoneInfo(settings.tz))

    cached = await load_cached(redis)
    age = _age_seconds(cached, now) if cached is not None else None
    if cached is not None and age is not None and age < FRESHNESS_SECONDS:
        return _serve(cached, stale=False)

    if await acquire_refresh_lock(redis) is False:
        # A peer is already fetching; never pile onto the school.
        return _serve(cached, stale=True)
    try:
        breaker = build_breaker(redis, settings)
        if not await breaker.admit():
            return _serve(cached, stale=True)
        try:
            html = await fetch_front_page()
            schedule = parse_front_schedule(html, tz=ZoneInfo(settings.tz))
        except SelcrsUnavailable:
            await breaker.record_unknown()
            return _serve(cached, stale=True)
        await breaker.record_classified()
        payload = _to_response(schedule, fetched_at=now)
        await save_cached(redis, payload)
        return _serve(payload, stale=False)
    finally:
        await release_refresh_lock(redis)
