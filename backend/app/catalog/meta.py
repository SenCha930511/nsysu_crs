"""Latest ingest-run meta reader (todo 6; consumed by todo 7's /api/catalog/meta)."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.courses import IngestRun


@dataclass(frozen=True, slots=True)
class CatalogMeta:
    """The newest ingest round's outcome. ``row_count`` is None on failed
    rounds (nothing was stored); ``updated_at`` falls back to the round's
    start time while the round is still running."""

    ok: bool
    updated_at: datetime
    row_count: int | None
    source: str


async def latest_catalog_meta(session: AsyncSession) -> CatalogMeta | None:
    """Meta for the newest ingest_runs row; None before any round ever ran."""
    run = (
        await session.execute(
            select(IngestRun).order_by(IngestRun.started_at.desc()).limit(1)
        )
    ).scalar_one_or_none()
    if run is None:
        return None
    return CatalogMeta(
        ok=run.ok,
        updated_at=run.finished_at if run.finished_at is not None else run.started_at,
        row_count=run.rows,
        source=run.source,
    )
