"""Alembic environment: async engine (asyncpg) wired to app Settings.

DATABASE_URL comes from process env or .env via app.config.Settings; the
plain `postgresql://` scheme is upgraded to the asyncpg dialect here.
"""

from logging.config import fileConfig
from typing import Final

import anyio
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

# Importing the package registers every table on Base.metadata.
import app.models  # noqa: F401  (side effect: model registration for autogenerate)
from alembic import context
from app.config import Settings
from app.models.base import Base

_ASYNCPG_PREFIX: Final = "postgresql+asyncpg://"

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    url = Settings().database_url
    if url.startswith("postgresql://"):
        return _ASYNCPG_PREFIX + url.removeprefix("postgresql://")
    return url


def _run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, default={})
    section["sqlalchemy.url"] = _database_url()
    connectable = async_engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    anyio.run(_run_migrations_online)
