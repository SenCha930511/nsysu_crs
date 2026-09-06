"""Site sessions and the Redis-only selcrs credential store (plan todo 8).

Site session: opaque random id in an httpOnly+SameSite=Lax cookie (``Secure``
only when served over HTTPS, see ``cookie_secure``); the row lives as
``site_session:{session_id} -> student_no`` with a 7-day SLIDING TTL
refreshed on every authenticated touch.

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

from fastapi import Request

from app.auth.redis_iface import AuthRedis

#: Site session sliding TTL: 7 days, plan-pinned (not env-driven).
SITE_SESSION_TTL_SECONDS: Final = 7 * 24 * 3600

SESSION_COOKIE_NAME: Final = "session_id"


def cookie_secure(request: Request) -> bool:
    """Transport-derived ``Secure`` flag for session/CSRF cookies.

    Emitted only when the request arrived over HTTPS. Declaring it flat-out
    on plain HTTP breaks Safari/WebKit, which (strict RFC 6265 §4.1.2.5)
    silently REFUSES to store a ``Secure`` cookie from ``http://localhost``;
    Chromium grants a localhost exemption, which is how every Brave-driven
    QA pass stayed green while Safari users looped login-200 → next-401 →
    /login?reason=expired (app logs 2026-08-28 12:41:58/12:42:12).
    """
    return request.url.scheme == "https"


def _site_key(session_id: str) -> str:
    return f"site_session:{session_id}"


def _selcrs_key(session_id: str) -> str:
    return f"selcrs:{session_id}"


def _selcrs_hard_key(session_id: str) -> str:
    return f"selcrs_hard:{session_id}"


def _selections_key(session_id: str) -> str:
    return f"selections:{session_id}"


def _grades_key(session_id: str) -> str:
    return f"grades:{session_id}"


def _regweb_key(session_id: str) -> str:
    return f"regweb:{session_id}"


def _regweb_hard_key(session_id: str) -> str:
    return f"regweb_hard:{session_id}"


def _stusco_key(session_id: str) -> str:
    return f"stusco:{session_id}"


def _stusco_hard_key(session_id: str) -> str:
    return f"stusco_hard:{session_id}"


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
    Same story for the two stu_enroll jar families (plan §5.3) and the
    grades snapshot (M2).
    """
    await redis.delete(
        _site_key(session_id),
        _selcrs_key(session_id),
        _selcrs_hard_key(session_id),
        _selections_key(session_id),
        _regweb_key(session_id),
        _regweb_hard_key(session_id),
        _stusco_key(session_id),
        _stusco_hard_key(session_id),
        _grades_key(session_id),
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


async def _store_jar_pair(
    redis: AuthRedis,
    key: str,
    hard_key: str,
    jar_payload: str,
    *,
    sliding_ttl: int,
    hard_ttl: int,
) -> None:
    """Family jar at login: sliding freshness; NX hard cap anchored at issuance."""
    await redis.set(key, jar_payload, ex=sliding_ttl)
    await redis.set(hard_key, "1", nx=True, ex=hard_ttl)


async def _load_jar_pair(
    redis: AuthRedis, key: str, hard_key: str, *, sliding_ttl: int
) -> str | None:
    """Family jar for a school call; None when sliding lapsed or hard cap died
    (the jar is then dropped eagerly). Survivors refresh sliding only."""
    if await redis.get(hard_key) is None:
        await redis.delete(key)
        return None
    payload = await redis.get(key)
    if payload is None:
        return None
    await redis.expire(key, sliding_ttl)
    return payload


async def store_regweb(
    redis: AuthRedis,
    session_id: str,
    jar_payload: str,
    *,
    sliding_ttl: int,
    hard_ttl: int,
) -> None:
    """Park the regweb jar (stu_enroll chain; covers tfstu/verify relays)."""
    await _store_jar_pair(
        redis,
        _regweb_key(session_id),
        _regweb_hard_key(session_id),
        jar_payload,
        sliding_ttl=sliding_ttl,
        hard_ttl=hard_ttl,
    )


async def load_regweb(redis: AuthRedis, session_id: str, *, sliding_ttl: int) -> str | None:
    """Regweb jar for a tfstu/verify-bound call, or None when expired."""
    return await _load_jar_pair(
        redis, _regweb_key(session_id), _regweb_hard_key(session_id), sliding_ttl=sliding_ttl
    )


async def store_stusco(
    redis: AuthRedis,
    session_id: str,
    jar_payload: str,
    *,
    sliding_ttl: int,
    hard_ttl: int,
) -> None:
    """Park the sco jar (own interactive login; covers the grade queries)."""
    await _store_jar_pair(
        redis,
        _stusco_key(session_id),
        _stusco_hard_key(session_id),
        jar_payload,
        sliding_ttl=sliding_ttl,
        hard_ttl=hard_ttl,
    )


async def load_stusco(redis: AuthRedis, session_id: str, *, sliding_ttl: int) -> str | None:
    """sco jar for a grade-query call, or None when expired."""
    return await _load_jar_pair(
        redis, _stusco_key(session_id), _stusco_hard_key(session_id), sliding_ttl=sliding_ttl
    )


async def subsystem_availability(redis: AuthRedis, session_id: str) -> tuple[bool, bool]:
    """(regweb_available, sco_available) by jar presence for the /auth/me
    response - a flag-off environment simply never parks them, so the UI
    flags read unavailable with zero feature-flag plumbing."""
    regweb_available = await redis.get(_regweb_key(session_id)) is not None
    sco_available = await redis.get(_stusco_key(session_id)) is not None
    return regweb_available, sco_available
