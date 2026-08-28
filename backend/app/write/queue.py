"""Write-queue Redis ticket (plan todo 15).

The ticket is the ONLY place a write job's execution context lives beyond
Postgres: ``session_ref`` (the site-session id whose ``selcrs:{ref}`` jar the
worker acts under) is credential-adjacent state and therefore NEVER enters
Postgres — exactly like the jar itself (Redis-only credential policy). The
Redis instance is pinned ``noeviction``; if a ticket is ever lost, the
orphaned queued job is dwell-cancelled honestly at WRITE_QUEUE_DWELL_MAX.

Payload whitelist (plan: "queue payload whitelist test: NO password-like /
secret fields"): the model's fields ARE the whitelist — a ticket never
carries a password, cookie value, CSRF token, or jar payload, and the
round-trip test asserts the key set verbatim.
"""

from collections.abc import Awaitable
from typing import Final, Protocol

from pydantic import BaseModel, ConfigDict

#: FIFO list of serialized QueueTickets; the single-worker loop BRPOs it.
WRITE_QUEUE_KEY: Final = "writeq:jobs"


class QueueRedis(Protocol):
    """Exactly what ``enqueue_ticket`` needs: the producer side of the FIFO.

    Plain ``def`` returning ``Awaitable`` so both ``AuthRedis`` (the API
    boundary dependency) and the real ``redis.asyncio.Redis`` satisfy it
    (redis-py stubs type aio methods as returning ``Awaitable``)."""

    def rpush(self, name: str, *values: str) -> Awaitable[int]: ...


class QueueTicket(BaseModel):
    """One enqueued write job: the confirm record's identity + session ref.

    ``canonical_ops`` is the canonical SEGMENTS string; the worker re-derives
    ops and payload_hash from it (with student_no), so a forged ticket cannot
    mint an arbitrary batch — Postgres idempotency is keyed on the re-derived
    hash, not on anything the queue asserts.
    """

    model_config = ConfigDict(frozen=True)

    job_id: str
    session_ref: str
    student_no: str
    canonical_ops: str
    variant: str
    form_url: str


#: The pinned whitelist asserted by tests (a new field needs a new look).
TICKET_FIELDS: Final = frozenset(QueueTicket.model_fields)


def serialize_ticket(ticket: QueueTicket) -> str:
    return ticket.model_dump_json()


def parse_ticket(payload: str) -> QueueTicket | None:
    """A corrupt ticket degrades to None (logged + discarded by the loop; a
    poison entry must never kill the single consumer)."""
    try:
        return QueueTicket.model_validate_json(payload)
    except ValueError:
        return None


async def enqueue_ticket(redis: QueueRedis, ticket: QueueTicket) -> None:
    """RPUSH onto the FIFO; called AFTER the job row commits so a popped
    ticket always finds its durable ledger row."""
    await redis.rpush(WRITE_QUEUE_KEY, serialize_ticket(ticket))
