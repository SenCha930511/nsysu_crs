"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.catalog import router as catalog_router
from app.api.courses import router as courses_router
from app.api.health import router as health_router
from app.config import Settings
from app.db import build_engine, build_session_factory


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app. Tests inject a constructed Settings; prod parses env."""
    resolved = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        await app.state.db_engine.dispose()

    app = FastAPI(title="NSYSU Course Wrapper", version="0.1.0", lifespan=lifespan)
    app.state.settings = resolved
    # Runtime engine + per-request session factory (todo 7); disposed on shutdown.
    app.state.db_engine = build_engine(resolved)
    app.state.session_factory = build_session_factory(app.state.db_engine)
    app.include_router(health_router)
    app.include_router(catalog_router)
    app.include_router(courses_router)
    return app
