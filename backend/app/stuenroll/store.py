"""Grades snapshot cache + sync diff - mirrors app/selections/store.py.

Same cache policy: the synced grades list lives ONLY in Redis, keyed by the
site session - ``grades:{session_id}`` - with a 7-day TTL (the site session
window). Purged on logout or by TTL; deliberately NO Postgres persistence.

Diff semantics: identity is the full verbatim cell tuple (rows are not keyed
entities on the school side), so ``added``/``removed``/``unchanged`` report
exactly row appearance / disappearance / survival in snapshot order.
"""

from typing import Final

from pydantic import BaseModel, ConfigDict

from app.auth.redis_iface import AuthRedis
from app.auth.sessions import SITE_SESSION_TTL_SECONDS

GRADES_TTL_SECONDS: Final = SITE_SESSION_TTL_SECONDS


class GradesSnapshot(BaseModel):
    """The cached sync result: when + the verbatim row cells."""

    model_config = ConfigDict(frozen=True)

    synced_at: str
    items: list[list[str]]


def _grades_key(session_id: str) -> str:
    return f"grades:{session_id}"


def _row_identity(row: list[str]) -> str:
    return "\x1f".join(row)


def diff_grade_rows(
    previous: list[list[str]], current: list[list[str]]
) -> tuple[list[list[str]], list[list[str]], list[list[str]]]:
    """(added, removed, unchanged) by row identity; duplicates collapse."""
    previous_ids = {_row_identity(row) for row in previous}
    current_ids = {_row_identity(row) for row in current}
    added = [row for row in current if _row_identity(row) not in previous_ids]
    removed = [row for row in previous if _row_identity(row) not in current_ids]
    unchanged = [row for row in current if _row_identity(row) in previous_ids]
    return added, removed, unchanged


async def load_grades_snapshot(redis: AuthRedis, session_id: str) -> GradesSnapshot | None:
    """The cached snapshot, or None when never synced / purged / TTL'd;
    a corrupt payload degrades to None (cache, not state of record)."""
    payload = await redis.get(_grades_key(session_id))
    if payload is None:
        return None
    try:
        return GradesSnapshot.model_validate_json(payload)
    except ValueError:
        return None


async def store_grades_snapshot(
    redis: AuthRedis, session_id: str, snapshot: GradesSnapshot
) -> None:
    """Replace the snapshot with a fresh 7-day TTL (logout/TTL purges it)."""
    await redis.set(
        _grades_key(session_id), snapshot.model_dump_json(), ex=GRADES_TTL_SECONDS
    )


async def delete_grades(redis: AuthRedis, session_id: str) -> None:
    """Logout wiring helper: drop the grades row with the rest of the session."""
    await redis.delete(_grades_key(session_id))
