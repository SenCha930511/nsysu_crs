"""Pool resilience (todo 17 hardening, debt a): ``pool_pre_ping=True``.

Skipped entirely when no Postgres is reachable; READ-ONLY statements only
(SELECT / pg_stat_activity / pg_terminate_backend of our OWN backend), so no
``CATALOG_DB_DESTRUCTIVE`` opt-in applies.

The test kills the pool's own idle backend out-of-band (an independent
asyncpg connection - never a second pooled engine connection, which would
sit on top of the pool's LIFO stack and make the assertion vacuous), waits
for the backend to disappear from ``pg_stat_activity``, then checks the
stale entry out again. With ``pool_pre_ping`` the checkout probe detects
the dead socket and transparently reconnects; without it the execute would
raise. That behavior - not any private pool attribute - is the pin.
"""

import anyio
import asyncpg
import pytest
from sqlalchemy import text

from app.config import Settings
from app.db import build_engine


def _db_available() -> bool:
    async def probe() -> bool:
        try:
            engine = build_engine(Settings())
            async with engine.connect():
                pass
            await engine.dispose()
            return True
        except OSError:
            return False

    return anyio.run(probe)


pytestmark = pytest.mark.skipif(not _db_available(), reason="compose Postgres unreachable")


def test_pool_pre_ping_resurrects_stale_connection():
    async def go() -> None:
        settings = Settings()
        engine = build_engine(settings)
        try:
            # Given: a live pooled connection, returned to the pool.
            async with engine.connect() as conn:
                pid = await conn.scalar(text("SELECT pg_backend_pid()"))
            assert isinstance(pid, int)

            # When: that idle backend is terminated out-of-band.
            plain_dsn = settings.database_url.removeprefix("postgresql://")
            raw = await asyncpg.connect(f"postgresql://{plain_dsn}")
            try:
                await raw.execute("SELECT pg_terminate_backend($1)", pid)
                gone = False
                for _ in range(40):  # bounded wait for the FATAL to land (<=2s)
                    exists = await raw.fetchval(
                        "SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE pid=$1)", pid
                    )
                    if not exists:
                        gone = True
                        break
                    await anyio.sleep(0.05)
                assert gone, "terminated backend never left pg_stat_activity"
            finally:
                await raw.close()

            # Then: the stale pooled entry (LIFO: the same one) is detected by
            # the checkout pre-ping, recycled, and the query just works.
            async with engine.connect() as conn:
                assert await conn.scalar(text("SELECT 1")) == 1
        finally:
            await engine.dispose()

    anyio.run(go)
