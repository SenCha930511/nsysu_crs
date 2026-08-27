"""Tests-for-health endpoint (tests-after strategy, per .omo plan)."""

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app import main as app_main
from app.api import health as health_module
from app.config import Settings


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _test_settings() -> Settings:
    return Settings(
        database_url="postgresql://user:pw@db-host.invalid:5432/wrapper",
        redis_url="redis://redis-host.invalid:6379/0",
        app_secret="test-secret",
    )


def test_health_returns_200_when_dependencies_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given a backend whose postgres and redis probes both succeed
    async def ok_probe(_: str) -> health_module.DependencyHealth:
        return health_module.DependencyHealth(status="ok")

    monkeypatch.setattr(health_module, "_probe_postgres", ok_probe)
    monkeypatch.setattr(health_module, "_probe_redis", ok_probe)
    client = TestClient(app_main.create_app(_test_settings()))

    # When GET /api/health is called
    response = client.get("/api/health")

    # Then it reports 200 with both dependencies ok
    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["status"] == "ok"
    assert body["postgres"]["status"] == "ok"
    assert body["redis"]["status"] == "ok"


def test_health_returns_503_without_internals_when_db_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a backend whose postgres probe fails but redis is fine
    async def pg_down(_: str) -> health_module.DependencyHealth:
        return health_module.DependencyHealth(status="down", error="ConnectionRefusedError")

    async def redis_ok(_: str) -> health_module.DependencyHealth:
        return health_module.DependencyHealth(status="ok")

    monkeypatch.setattr(health_module, "_probe_postgres", pg_down)
    monkeypatch.setattr(health_module, "_probe_redis", redis_ok)
    client = TestClient(app_main.create_app(_test_settings()))

    # When GET /api/health is called
    response = client.get("/api/health")

    # Then it is 503, flags postgres as down, and leaks no DSN/credential material
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["postgres"]["status"] == "down"
    assert body["redis"]["status"] == "ok"
    for needle in ("db-host.invalid", "redis-host.invalid", "user:pw", "postgresql://", "redis://"):
        assert needle not in response.text


@pytest.mark.anyio
async def test_probe_postgres_reports_down_for_unreachable_host() -> None:
    # Given a DSN pointing at a closed local port (exercises the REAL probe path)
    # When the probe runs
    result = await health_module._probe_postgres("postgresql://127.0.0.1:9/wrapper")

    # Then it reports down with a sanitized error (no URL material)
    assert result.status == "down"
    assert result.error is not None
    assert "postgresql://" not in result.error


@pytest.mark.anyio
async def test_probe_redis_reports_down_for_unreachable_host() -> None:
    # Given a URL pointing at a closed local port (exercises the REAL probe path)
    # When the probe runs
    result = await health_module._probe_redis("redis://127.0.0.1:9/0")

    # Then it reports down with a sanitized error (no URL material)
    assert result.status == "down"
    assert result.error is not None
    assert "redis://" not in result.error
