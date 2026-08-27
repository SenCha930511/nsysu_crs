"""GET /api/catalog/meta - freshness contract for the frontend (plan todo 7).

Always answers 200, even when the newest ingest round failed (ok=false) or no
round ever ran (nulls): the frontend reads ``ok``/``updated_at`` to drive its
stale-data banner (todo 10), so a failed crawl must NOT break this endpoint.
"""

from datetime import datetime
from typing import Final

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.catalog.meta import CatalogMeta, latest_catalog_meta

router: Final = APIRouter()


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
