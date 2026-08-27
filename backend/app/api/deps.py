"""Shared FastAPI dependencies for the API routers (plan todo 7)."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request, status
from fastapi.exceptions import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.redis_iface import AuthRedis
from app.auth.sessions import SESSION_COOKIE_NAME, resolve_site_session


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One AsyncSession per request; factory lives on app.state (todo 7 wiring)."""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        yield session


def get_redis(request: Request) -> AuthRedis:
    """The process-wide Redis client (built in lifespan; decode_responses)."""
    return request.app.state.redis


async def get_current_student(
    request: Request, redis: Annotated[AuthRedis, Depends(get_redis)]
) -> str:
    """student_no of the current site session, else a flat 401.

    One code for missing/expired/unknown sessions (``not_authenticated``):
    like CREDENTIAL-FAIL, presence and expiry are deliberately
    indistinguishable from the outside. Resolving refreshes the 7-day
    sliding TTL (activity keeps a session warm).
    """
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    student_no = (
        await resolve_site_session(redis, session_id) if session_id is not None else None
    )
    if student_no is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="not_authenticated"
        )
    return student_no
