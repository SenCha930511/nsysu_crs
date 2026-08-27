"""Async engine / session factory for app code (worker, API, QA scripts).

Alembic env.py builds its own migration engine; this module is the runtime
sibling for everything else. ``postgresql://`` URLs are upgraded to the
asyncpg dialect here, exactly matching alembic env.py's policy.
"""

from typing import Final

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings

_ASYNCPG_PREFIX: Final = "postgresql+asyncpg://"


def async_url(database_url: str) -> str:
    """Upgrade a plain ``postgresql://`` URL to the asyncpg dialect."""
    if database_url.startswith("postgresql://"):
        return _ASYNCPG_PREFIX + database_url.removeprefix("postgresql://")
    return database_url


def build_engine(settings: Settings) -> AsyncEngine:
    """One engine per process (pool defaults are fine: ingest is serialized
    by the Redis singleton lock; the API layer is added in todo 7)."""
    return create_async_engine(async_url(settings.database_url))


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """``expire_on_commit=False``: ledger rows (ingest_runs) are read back
    after commit by the meta reader without re-hitting the DB."""
    return async_sessionmaker(engine, expire_on_commit=False)
