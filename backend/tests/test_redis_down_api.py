"""Redis-down honesty (plan todo 15 Acceptance): when Redis is down, the
credential-bearing paths (login + every /api/write/*) hard-fail 503 with a
uniform detail - never a 500, never partially executed - while Postgres
reads are unaffected (proven live in qa/15-redisdown.log; they never touch
Redis by construction, see app/api/courses.py + app/api/catalog.py)."""

import uuid

import pytest
from fastapi.testclient import TestClient
from redis.exceptions import RedisError

from app.config import Settings
from app.main import create_app
from app.write.csrf import csrf_cookie_name


class DownRedis:
    """An AuthRedis-shaped double raising on every call (scripted outage)."""

    async def get(self, name): raise RedisError("scripted outage")
    async def getdel(self, name): raise RedisError("scripted outage")
    async def set(self, name, value, *, nx=False, ex=None): raise RedisError("scripted outage")
    async def delete(self, *names): raise RedisError("scripted outage")
    async def incr(self, name): raise RedisError("scripted outage")
    async def expire(self, name, time, *, nx=False): raise RedisError("scripted outage")
    async def zadd(self, name, mapping): raise RedisError("scripted outage")
    async def zremrangebyscore(self, name, min, max): raise RedisError("scripted outage")
    async def zcard(self, name): raise RedisError("scripted outage")
    async def rpush(self, name, *values): raise RedisError("scripted outage")


@pytest.fixture
def client():
    app = create_app(Settings(app_secret="qa15-redisdown-secret"))
    with TestClient(app, raise_server_exceptions=True) as test_client:
        test_client.app.state.redis = DownRedis()
        yield test_client


def _write_headers() -> dict:
    session_id = "deadbeef" * 4
    return {
        "cookies": {"session_id": session_id, csrf_cookie_name(session_id): "pair"},
        "headers": {"X-CSRF-Token": "pair"},
    }


def test_login_hard_fails_503_when_redis_is_down(client):
    response = client.post(
        "/api/auth/login", json={"student_no": "M153000024", "password": "whatever"}
    )
    assert (response.status_code, response.json()) == (
        503,
        {"detail": "redis_unavailable"},
    )


def test_write_preview_hard_fails_503_when_redis_is_down(client):
    response = client.post(
        "/api/write/preview",
        json={"ops": [{"action": "+", "course_id": "GEAE2526", "priority": 1}]},
        **_write_headers(),
    )
    assert (response.status_code, response.json()) == (
        503,
        {"detail": "redis_unavailable"},
    )


def test_write_submit_hard_fails_503_when_redis_is_down(client):
    response = client.post(
        "/api/write/submit",
        json={"confirm_token": "whatever", "password": "whatever"},
        **_write_headers(),
    )
    assert (response.status_code, response.json()) == (
        503,
        {"detail": "redis_unavailable"},
    )


def test_write_jobs_hard_fails_503_when_redis_is_down(client):
    response = client.get(f"/api/write/jobs/{uuid.uuid4()}", **_write_headers())
    assert (response.status_code, response.json()) == (
        503,
        {"detail": "redis_unavailable"},
    )


def test_csrf_gate_still_applies_with_redis_down(client):
    response = client.post(
        "/api/write/submit", json={"confirm_token": "x", "password": "y"}
    )
    assert (response.status_code, response.json()) == (403, {"detail": "csrf_failed"})
