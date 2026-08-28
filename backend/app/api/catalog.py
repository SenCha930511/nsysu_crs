"""GET /api/catalog/meta - freshness contract for the frontend (plan todo 7).

Always answers 200, even when the newest ingest round failed (ok=false) or no
round ever ran (nulls): the frontend reads ``ok``/``updated_at`` to drive its
stale-data banner (todo 10), so a failed crawl must NOT break this endpoint.
"""

import json
import logging
from datetime import datetime
from typing import Annotated, Final

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_redis, get_session
from app.auth.redis_iface import AuthRedis
from app.catalog.meta import CatalogMeta, latest_catalog_meta
from app.models.courses import Course

router: Final = APIRouter()

_DEPTS_CACHE_TTL: Final = 1800  # seconds; the catalog layer only moves on ingest ticks, so 30 min is plenty.


class CatalogMetaResponse(BaseModel):
    """Payload for the newest ingest_runs row (nulls before any round ran)."""

    model_config = ConfigDict(frozen=True)

    ok: bool
    updated_at: datetime | None
    row_count: int | None
    source: str


def meta_payload(meta: CatalogMeta | None) -> CatalogMetaResponse:
    """Pure mapping: None (never ingested) degrades to ok=false + nulls."""
    if meta is None:
        return CatalogMetaResponse(
            ok=False, updated_at=None, row_count=None, source="self-scrape"
        )
    return CatalogMetaResponse(
        ok=meta.ok,
        updated_at=meta.updated_at,
        row_count=meta.row_count,
        source=meta.source,
    )


@router.get("/api/catalog/meta", response_model=CatalogMetaResponse)
async def get_catalog_meta(
    session: AsyncSession = Depends(get_session),
) -> CatalogMetaResponse:
    return meta_payload(await latest_catalog_meta(session))


class DeptsResponse(BaseModel):
    """Distinct dept strings as stored verbatim from the school catalog."""

    model_config = ConfigDict(frozen=True)

    departments: list[str]


_DEPTS_CACHE_KEY: Final = "crs:catalog:depts"


@router.get("/api/catalog/depts", response_model=None)
async def list_catalog_depts(
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[AuthRedis, Depends(get_redis)],
) -> JSONResponse:
    """The department/學系 dropdown options: distinct ``courses.dept`` values
    (they ride the school's own row wording moment-to-moment; never fabricated)."""
    cached = await redis.get(_DEPTS_CACHE_KEY)
    if cached is not None:
        return JSONResponse(status_code=status.HTTP_200_OK, content=json.loads(cached))
    rows = (
        await session.execute(
            select(Course.dept)
            .where(Course.dept.is_not(None), Course.dept != "")
            .distinct()
            .order_by(Course.dept)
        )
    ).scalars().all()
    payload = DeptsResponse(
        departments=[dept for dept in rows if dept is not None]
    ).model_dump()
    try:
        await redis.set(
            _DEPTS_CACHE_KEY, json.dumps(payload, ensure_ascii=False), ex=_DEPTS_CACHE_TTL
        )
    except RedisError as exc:
        logging.getLogger(__name__).warning(
            "depts cache write skipped (redis unavailable): %s", exc
        )
    return JSONResponse(status_code=status.HTTP_200_OK, content=payload)
