"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError

from app.api.auth import router as auth_router
from app.api.catalog import router as catalog_router
from app.api.courses import router as courses_router
from app.api.health import router as health_router
from app.api.plans import router as plans_router
from app.api.plans_export import router as plans_export_router
from app.api.selections import router as selections_router
from app.api.stage import router as stage_router
from app.api.write import router as write_router
from app.api.write_jobs import router as write_jobs_router
from app.api.write_submit import router as write_submit_router
from app.config import Settings
from app.db import build_engine, build_session_factory
from app.write.csrf import CsrfMiddleware


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app. Tests inject a constructed Settings; prod parses env."""
    resolved = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Lazy-connect (no dial at startup): Redis outage must not kill boot; reads stay up.
        redis_client = aioredis.Redis.from_url(resolved.redis_url, decode_responses=True)
        app.state.redis = redis_client
        yield
        await redis_client.aclose()
        await app.state.db_engine.dispose()

    app = FastAPI(title="NSYSU Course Wrapper", version="0.1.0", lifespan=lifespan)
    app.state.settings = resolved
    # Runtime engine + per-request session factory (todo 7); disposed on shutdown.
    app.state.db_engine = build_engine(resolved)
    app.state.session_factory = build_session_factory(app.state.db_engine)

    @app.exception_handler(RedisError)
    async def redis_unavailable_handler(
        _request: Request, _exc: RedisError
    ) -> JSONResponse:
        """Redis-down honesty (plan todo 15 Acceptance): every credential /
        write path hard-fails 503 while Postgres-backed reads (courses,
        catalog meta) never touch Redis and keep serving."""
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "redis_unavailable"},
        )

    app.add_middleware(CsrfMiddleware)
    app.include_router(health_router)
    app.include_router(catalog_router)
    app.include_router(courses_router)
    app.include_router(auth_router)
    app.include_router(selections_router)
    app.include_router(plans_router)
    app.include_router(plans_export_router)
    app.include_router(stage_router)
    app.include_router(write_router)
    app.include_router(write_submit_router)
    app.include_router(write_jobs_router)
    return app
