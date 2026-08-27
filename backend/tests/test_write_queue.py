"""Write-queue ticket tests (plan todo 15): the whitelist is THE credential
boundary - queue payloads must never smell like passwords/cookies/secrets -
plus the consumer loop's pop-and-execute wiring."""

import json

import anyio
import pytest

from app.write.queue import (
    TICKET_FIELDS,
    WRITE_QUEUE_KEY,
    QueueTicket,
    enqueue_ticket,
    parse_ticket,
    serialize_ticket,
)
from app.write.queue_loop import write_queue_loop
from tests.fake_redis import FakeRedis

TICKET = QueueTicket(
    job_id="5f9c2b9e-3a78-4b1d-9a1c-9a1111111111",
    session_ref="site-session-ref-0123456789abcdef",
    student_no="M153000024",
    canonical_ops="-:M3046243:|+:GEAE2526:01",
    variant="ssform",
    form_url="https://selcrs.nsysu.edu.tw/menu4/addcourse/ssform.asp?X1=09",
)

#: Substrings that must NEVER appear in a queue payload (case-insensitive).
SECRET_DENYLIST = ("password", "spassword", "cookie", "secret", "csrf", "jar", "bearer")


def test_ticket_fields_are_the_whitelist():
    assert TICKET_FIELDS == frozenset(
        {"job_id", "session_ref", "student_no", "canonical_ops", "variant", "form_url"}
    )


def test_serialized_ticket_carries_only_whitelisted_fields_and_no_secret_shape():
    payload = serialize_ticket(TICKET)
    parsed = json.loads(payload)
    assert set(parsed) == TICKET_FIELDS
    folded = payload.lower()
    for denied in SECRET_DENYLIST:
        assert denied not in folded
    # No credential VALUES may leak either.
    assert "QA-SECRET" not in payload
    assert "ASPSESSIONID" not in payload
    assert "base64" not in folded


def test_roundtrip_and_corrupt_payload():
    assert parse_ticket(serialize_ticket(TICKET)) == TICKET
    assert parse_ticket("{not json") is None
    assert parse_ticket(json.dumps({"job_id": 1})) is None


@pytest.mark.anyio
async def test_enqueue_rpush_onto_the_fifo():
    redis = FakeRedis()
    await enqueue_ticket(redis, TICKET)
    listing = await redis.lrange(WRITE_QUEUE_KEY, 0, -1)
    assert listing == [serialize_ticket(TICKET)]


@pytest.mark.anyio
async def test_loop_executes_a_popped_ticket_and_sweeps(monkeypatch):
    executed: list[QueueTicket] = []
    sweeps: list[int] = []

    async def stub_execute(ticket, ctx):
        executed.append(ticket)

    async def stub_sweep(ctx):
        sweeps.append(1)

        class Report:
            cancelled = 0

        return Report()

    monkeypatch.setattr("app.write.queue_loop.execute_ticket", stub_execute)
    monkeypatch.setattr("app.write.queue_loop.sweep_once", stub_sweep)

    redis = FakeRedis()
    await enqueue_ticket(redis, TICKET)

    async def pop() -> str | None:
        popped = await redis.brpop([WRITE_QUEUE_KEY], timeout=0)
        if popped is None:
            await anyio.sleep(0.01)  # behave like the timed BRPOP
            return None
        return popped[1]

    with anyio.move_on_after(0.2):
        await write_queue_loop(None, pop=pop, sweep_interval=0.05)  # type: ignore[arg-type]

    assert executed == [TICKET]
    assert sweeps  # the dwell sweep ran at startup
