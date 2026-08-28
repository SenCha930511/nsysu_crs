#!/usr/bin/env python3
"""One-shot local backfill: courses.code <- CrsDat= from courses.url.

Safe, read-derive-write against the local DB only (zero school traffic): the
課別代號 already lives in every row's showoutline link, parsed by
``app.catalog.parse`` at ingest from now on (2026-08-28 identifier discovery);
this script heals rows ingested before that change without waiting for the
next snapshot-replace tick.

Usage (inside the app container the compose db is resolvable from):
    docker compose -f deploy/docker-compose.yml cp scripts/backfill_codes.py app:/tmp/
    docker compose -f deploy/docker-compose.yml exec -T app \
      sh -lc 'cd /app && uv run --no-dev python /tmp/backfill_codes.py [--dry-run]'
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="count only, no UPDATE")
    args = parser.parse_args()

    dsn = os.environ.get("DATABASE_URL")
    if dsn is None:
        raise SystemExit("DATABASE_URL is not set")
    # Container env carries the psycopg-less plain scheme; asyncpg is the only
    # installed async driver (same normalization the app performs).
    dsn = dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(dsn)
    async with async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)() as session:
        total = (
            await session.execute(text("select count(*) from courses where url like '%CrsDat=%'"))
        ).scalar_one()
        missing = (
            await session.execute(
                text("select count(*) from courses where code is null and url like '%CrsDat=%'")
            )
        ).scalar_one()
        print(f"[backfill] rows carrying CrsDat: {total}; still null-code: {missing}", flush=True)
        if args.dry_run:
            print("[backfill] dry-run: no UPDATE issued", flush=True)
            return
        result = await session.execute(
            text(
                "update courses set code = substring(url from 'CrsDat=([^&]*)') "
                "where code is null and url like '%CrsDat=%'"
            )
        )
        await session.commit()
        print(f"[backfill] updated rows: {result.rowcount}", flush=True)
        remaining = (
            await session.execute(text("select count(*) from courses where code is null"))
        ).scalar_one()
        print(f"[backfill] remaining null-code rows (no CrsDat url): {remaining}", flush=True)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
