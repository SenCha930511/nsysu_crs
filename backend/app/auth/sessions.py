"""Site sessions and the Redis-only selcrs credential store (plan todo 8).

Site session: opaque random id in an httpOnly+Secure+SameSite=Lax cookie;
the row lives as ``site_session:{session_id} -> student_no`` with a 7-day
SLIDING TTL refreshed on every authenticated touch.

selcrs store: the school's session jar is a credential and lives ONLY here:

- ``selcrs:{session_id}``   — the serialized jar, SLIDING TTL
  (``SELCRS_SESSION_TTL_SLIDING``, default 1800s) refreshed on each school
  activity that consumes it (todo 9+);
- ``selcrs_hard:{session_id}`` — issued once with ``SET NX EX`` at login,
  HARD cap (``SELCRS_SESSION_TTL_HARD``, default 7200s): when it lapses the
  jar is dead no matter how recent the activity (sliding cannot outlive hard).

Never Postgres, never logs. Redis failure hard-fails login/write while read
paths stay available (a failed write raises; nothing here swallows it).
"""

import uuid
from typing import Final

from app.auth.redis_iface import AuthRedis

#: Site session sliding TTL: 7 days, plan-pinned (not env-driven).
SITE_SESSION_TTL_SECONDS: Final = 7 * 24 * 3600

SESSION_COOKIE_NAME: Final = "session_id"


def _site_key(session_id: str) -> str:
    return f"site_session:{session_id}"


def _selcrs_key(session_id: str) -> str:
    return f"selcrs:{session_id}"


def _selcrs_hard_key(session_id: str) -> str:
    return f"selcrs_hard:{session_id}"


def _selections_key(session_id: str) -> str:
    return f"selections:{session_id}"


async def create_site_session(redis: AuthRedis, student_no: str) -> str:
    """Mint a fresh site session id and store its owner (7d sliding)."""
    session_id = uuid.uuid4().hex
    await redis.set(_site_key(session_id), student_no, ex=SITE_SESSION_TTL_SECONDS)
    return session_id


async def resolve_site_session(redis: AuthRedis, session_id: str) -> str | None:
    """Owner of the site session, or None when missing/expired. Sliding refresh."""
    key = _site_key(session_id)
    student_no = await redis.get(key)
    if student_no is None:
        return None
    await redis.expire(key, SITE_SESSION_TTL_SECONDS)
    return student_no


async def delete_site_session(redis: AuthRedis, session_id: str) -> None:
    """Logout: drop the site session and every session-scoped row with it.

    Includes the todo-9 selections snapshot: session-scoped cache only,
    purged here (or by its own TTL) - never left to outlive the session.
    """
    await redis.delete(
        _site_key(session_id),
        _selcrs_key(session_id),
        _selcrs_hard_key(session_id),
        _selections_key(session_id),
    )


async def store_selcrs(
    redis: AuthRedis,
    session_id: str,
    jar_payload: str,
    *,
    sliding_ttl: int,
    hard_ttl: int,
) -> None:
    """Park a fresh school jar at login: sliding freshness + hard cap anchor."""
    await redis.set(_selcrs_key(session_id), jar_payload, ex=sliding_ttl)
    # NX anchors the hard cap at issuance; a same-id re-store can never push it out.
    await redis.set(_selcrs_hard_key(session_id), "1", nx=True, ex=hard_ttl)


async def load_selcrs(redis: AuthRedis, session_id: str, *, sliding_ttl: int) -> str | None:
    """Jar for a school-bound call (todo 9+), or None when expired.

    Expired means: the sliding window lapsed (jar key gone) OR the hard cap
    lapsed (anchor gone — the jar is then dropped eagerly, not read).
    Survivors get their sliding TTL refreshed (activity extends freshness,
    never the hard cap).
    """
    if await redis.get(_selcrs_hard_key(session_id)) is None:
        await redis.delete(_selcrs_key(session_id))
        return None
    key = _selcrs_key(session_id)
    payload = await redis.get(key)
    if payload is None:
        return None
    await redis.expire(key, sliding_ttl)
    return payload
