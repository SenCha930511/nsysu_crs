"""FastAPI application factory."""

from fastapi import FastAPI

from app.api.health import router as health_router
from app.config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app. Tests inject a constructed Settings; prod parses env."""
    app = FastAPI(title="NSYSU Course Wrapper", version="0.1.0")
    app.state.settings = settings if settings is not None else Settings()
    app.include_router(health_router)
    return app
