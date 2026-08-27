"""Selections snapshot cache + sync diff (plan todo 9).

Cache policy (task): the synced selections list lives ONLY in Redis, keyed by
the site session - ``selections:{session_id}`` - with a 7-day TTL (the site
session window). It is purged on logout (``delete_site_session`` drops this
key too) or by TTL; there is deliberately NO Postgres persistence for the
selections list.

Diff semantics: identity-set based. An item's identity is its 8-char
``code`` when present, else ``{course_no}|{name}`` (error-section rows carry
no code). ``added``/``removed`` are pure set differences (new-version items /
old-version items, in their snapshot order); ``unchanged`` are identities in
both snapshots (current version). An identity kept across syncs with changed
content (points re-prioritized, 登記加選 -> 選上) reports as unchanged - the
diff announces comings and goings, not field drift. First sync (no previous
snapshot): everything is added, nothing removed.
"""

from typing import Final

from pydantic import BaseModel, ConfigDict

from app.auth.redis_iface import AuthRedis
from app.auth.sessions import SITE_SESSION_TTL_SECONDS
from app.selections.parse import SelectionItem

SELECTIONS_TTL_SECONDS: Final = SITE_SESSION_TTL_SECONDS


class SelectionsSnapshot(BaseModel):
    """The cached sync result: when + the normalized items (post-join)."""

    model_config = ConfigDict(frozen=True)

    synced_at: str
    items: list[SelectionItem]


def _selections_key(session_id: str) -> str:
    return f"selections:{session_id}"


def item_identity(item: SelectionItem) -> str:
    """Stable diff key: the school code, else the course_no|name fallback."""
    if item.code is not None:
        return item.code
    return f"{item.course_no or ''}|{item.name}"


def diff_items(
    previous: list[SelectionItem], current: list[SelectionItem]
) -> tuple[list[SelectionItem], list[SelectionItem], list[SelectionItem]]:
    """(added, removed, unchanged) by identity; duplicate identities collapse."""
    previous_ids = {item_identity(item) for item in previous}
    current_ids = {item_identity(item) for item in current}
    added = [item for item in current if item_identity(item) not in previous_ids]
    removed = [item for item in previous if item_identity(item) not in current_ids]
    unchanged = [item for item in current if item_identity(item) in previous_ids]
    return added, removed, unchanged


async def load_snapshot(redis: AuthRedis, session_id: str) -> SelectionsSnapshot | None:
    """The cached snapshot, or None when never synced / purged / TTL'd.

    A corrupt payload degrades to None (cache, not state of record) rather
    than breaking the read path.
    """
    payload = await redis.get(_selections_key(session_id))
    if payload is None:
        return None
    try:
        return SelectionsSnapshot.model_validate_json(payload)
    except ValueError:
        return None


async def store_snapshot(
    redis: AuthRedis, session_id: str, snapshot: SelectionsSnapshot
) -> None:
    """Replace the snapshot with a fresh 7-day TTL (logout/TTL purges it)."""
    await redis.set(
        _selections_key(session_id),
        snapshot.model_dump_json(),
        ex=SELECTIONS_TTL_SECONDS,
    )


async def delete_selections(redis: AuthRedis, session_id: str) -> None:
    """Logout wiring: drop the selections row with the rest of the session."""
    await redis.delete(_selections_key(session_id))
