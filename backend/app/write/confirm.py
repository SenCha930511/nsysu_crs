"""confirm_token Redis store (plan todo 14; todo 15's confirm consumes it).

``confirm:{token}`` -> JSON of {student_no, canonical_ops, variant, form_url}
with TTL = CONFIRM_TOKEN_TTL (300s default; already in Settings).

Single-use: consumption is the atomic ``GETDEL`` (plan todo 14: "consume 必須
原子：以 GETDEL 或等價 Lua 完成，重放→409"). The first consumer gets the
record; any replay gets None, which the todo-15 confirm endpoint maps to
409. There is deliberately no non-destructive read here - a consumer who
only peeks would still spend the token.
"""

from typing import Final

from pydantic import BaseModel, ConfigDict

from app.auth.redis_iface import AuthRedis

_CONFIRM_KEY_PREFIX: Final = "confirm:"


class ConfirmRecord(BaseModel):
    """What a minted confirm_token entitles (recomputed at confirm time).

    ``canonical_ops`` is the canonical SEGMENTS string
    (``act:code:TT|...``, see app.write.canonical) - together with
    ``student_no`` it re-derives both the token and the payload_hash, with
    the server secret, so the stored value alone cannot mint anything.
    """

    model_config = ConfigDict(frozen=True)

    student_no: str
    canonical_ops: str
    variant: str
    form_url: str


def confirm_key(token: str) -> str:
    return f"{_CONFIRM_KEY_PREFIX}{token}"


async def store_confirm(
    redis: AuthRedis, token: str, record: ConfirmRecord, *, ttl: int
) -> None:
    """Mint: park the record under the token (fresh TTL; re-preview refreshes)."""
    await redis.set(confirm_key(token), record.model_dump_json(), ex=ttl)


async def consume_confirm(redis: AuthRedis, token: str) -> ConfirmRecord | None:
    """Single-use take (atomic GETDEL): record once, None forever after.

    A corrupt payload degrades to None (same 409 path as a replay - this
    store is write-path state of record for 5 minutes, never a cache to
    repair from).
    """
    payload = await redis.getdel(confirm_key(token))
    if payload is None:
        return None
    try:
        return ConfirmRecord.model_validate_json(payload)
    except ValueError:
        return None
