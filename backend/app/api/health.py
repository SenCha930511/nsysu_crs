"""Liveness/readiness health endpoint with per-dependency probes.

The response NEVER contains URLs, DSNs, credentials, or exception messages -
only the exception class name per failed dependency - so the endpoint is safe
to expose publicly.
"""

from typing import Final, Literal

import asyncpg
import redis.asyncio as redis_vendor
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.config import Settings

router: Final = APIRouter()

_PROBE_TIMEOUT_SECONDS: Final = 2.0


class DependencyHealth(BaseModel):
    """Health of one downstream dependency. `error` is an exception class name only."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok", "down"]
    error: str | None = None


class HealthResponse(BaseModel):
    """Aggregate health payload for /api/health."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok", "unavailable"]
    postgres: DependencyHealth
    redis: DependencyHealth


async def _probe_postgres(dsn: str) -> DependencyHealth:
    """Probe Postgres with `SELECT 1`; report downtime without leaking the DSN."""
    conn: asyncpg.Connection | None = None
    try:
        conn = await asyncpg.connect(dsn, timeout=_PROBE_TIMEOUT_SECONDS)
        await conn.fetchval("SELECT 1")
    except (OSError, TimeoutError, asyncpg.PostgresError, asyncpg.InterfaceError) as exc:
        result = DependencyHealth(status="down", error=type(exc).__name__)
    else:
        result = DependencyHealth(status="ok")
    if conn is not None:
        await conn.close()
    return result


async def _probe_redis(url: str) -> DependencyHealth:
    """Probe Redis with PING; report downtime without leaking the URL."""
    client = redis_vendor.from_url(
        url,
        socket_connect_timeout=_PROBE_TIMEOUT_SECONDS,
        socket_timeout=_PROBE_TIMEOUT_SECONDS,
    )
    try:
        await client.ping()
    except (OSError, TimeoutError, redis_vendor.RedisError) as exc:
        result = DependencyHealth(status="down", error=type(exc).__name__)
    else:
        result = DependencyHealth(status="ok")
    await client.aclose()
    return result


@router.get("/api/health")
async def get_health(request: Request) -> JSONResponse:
    """Return 200 when all dependencies are reachable, else 503 with sanitized details."""
    settings: Settings = request.app.state.settings
    postgres_health = await _probe_postgres(settings.database_url)
    redis_health = await _probe_redis(settings.redis_url)
    healthy = postgres_health.status == "ok" and redis_health.status == "ok"
    body = HealthResponse(
        status="ok" if healthy else "unavailable",
        postgres=postgres_health,
        redis=redis_health,
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
        content=body.model_dump(mode="json"),
    )
