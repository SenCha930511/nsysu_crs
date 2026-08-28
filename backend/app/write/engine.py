"""Write-submission execution engine (plan todo 15).

Pipeline per dequeued ticket (a job's phases; Postgres is the durable
ledger, Redis the wake-up channel):

1. CLAIM: atomic queued -> running, dwell-aware (jobs older than
   WRITE_QUEUE_DWELL_MAX are cancelled, never executed). An already
   superseded/cancelled job is not claimed - zero school contact.
2. FAIL-CLOSED AUDIT: one pending write_audit row per op, BEFORE any school
   contact. Insert failure -> job failed, the school is never called.
3. Session liveness: dead selcrs jar -> every op 階段逾時, job failed, no
   retry (plan: 過期→全課 階段逾時 終態不重試).
4. Same-session GET of the recorded form_url -> hidden-input replay ->
   D/C/T overwrite (todo-14 builders) -> POST the 送出-pinned submit endpoint
   (ssprs/saddstage5prs; the LIVE ssform's static action is the 暫存/draft
   endpoint, not the submit one - live-verified, sees app.write.payload) with
   Referer:<form_url> (adapter-pinned). Transport discipline: <=2 retries
   with the adapter backoff; business failures are terminal immediately.
5. Response is parsed per course code (app.write.response): the live
   canonical shape is a status snapshot + 【加退選失敗課程清單】 failure
   section; a transport-retried op answering duplicate-like becomes
   ``unknown-reconciled`` — never ``failed``, because the first POST may
   have landed.
6. Reconcile: when the POST was transport-retried and unknown-reconciled
   ops exist, one slt_result fetch (NEVER retried itself) upgrades those
   outcomes to their real state; a dead/superseded session leaves them
   unknown-reconciled for manual resync (surfaced by the jobs API).
7. Terminal write: job done when the batch executed end-to-end (mixed
   per-op verdicts included), failed for systemic pre-posting failures.
   finish_job is guarded non-terminal-only, so a mid-run session_superseded
   flip (new login, todo 8) is never clobbered.

Dwell sweep: queued/running jobs older than WRITE_QUEUE_DWELL_MAX ->
cancelled (also reaps jobs whose ticket Redis lost - the honest terminal).
"""

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Final
from urllib.parse import urljoin

import anyio
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.redis_iface import AuthRedis
from app.auth.sessions import load_selcrs
from app.config import Settings
from app.selcrs.endpoints import get_write_form, post_write
from app.selcrs.errors import SelcrsSessionExpired, SelcrsUnavailable
from app.selcrs.http import BACKOFF_SECONDS
from app.selcrs.jar import deserialize_cookies
from app.stage.detect import VARIANT_SSFORM, VARIANT_STAGE5
from app.write import jobs, reconcile
from app.write.canonical import parse_canonical_segments, payload_hash
from app.write.outcomes import (
    OUTCOME_FAILED,
    OUTCOME_PARSE_FAILED,
    OUTCOME_STAGE_EXPIRED,
    OUTCOME_SUPERSEDED,
    OUTCOME_TRANSPORT_FAILED,
    OUTCOME_UNKNOWN_RECONCILED,
)
from app.write.payload import (
    SEND_NAME,
    build_payload_ssprs,
    build_payload_stage5,
    parse_form_action,
    parse_form_hidden_inputs,
    parse_send_value,
    parse_submit_action,
    parse_submit_step,
)
from app.write.queue import QueueTicket
from app.write.response import is_session_bounce, parse_submit_response

_logger = logging.getLogger(__name__)

#: Plan-pinned write-path transport discipline (business failures: terminal).
TRANSPORT_RETRIES: Final = 2

_BUILDERS: Final = {VARIANT_SSFORM: build_payload_ssprs, VARIANT_STAGE5: build_payload_stage5}


@dataclass(frozen=True, slots=True)
class EngineContext:
    """Worker wiring; ``sleep``/``now`` are the test seams (injectable time)."""

    redis: AuthRedis
    session_factory: async_sessionmaker[AsyncSession]
    settings: Settings
    sleep: Callable[[float], Awaitable[None]] = field(default=anyio.sleep)
    now: Callable[[], datetime] = field(
        default=lambda: datetime.now(UTC)
    )


async def _transport_call[T](
    ctx: EngineContext, call: Callable[[], Awaitable[T]]
) -> tuple[T | None, bool]:
    """One adapter call under the <=2-retry discipline (adapter backoff
    waits). Returns (result, retried); (None, True) on exhaustion."""
    for attempt in range(TRANSPORT_RETRIES + 1):
        try:
            return await call(), attempt > 0
        except SelcrsUnavailable:
            if attempt == TRANSPORT_RETRIES:
                return None, True
            await ctx.sleep(BACKOFF_SECONDS[attempt])
    return None, True  # unreachable: the loop always returns


async def _current_status(ctx: EngineContext, job_id: uuid.UUID) -> str | None:
    async with ctx.session_factory() as session:
        return await jobs.read_job_status(session, job_id)


async def _finalize(
    ctx: EngineContext,
    job_id: uuid.UUID,
    updates: list[tuple[uuid.UUID, str, str | None]],
    status: str,
) -> None:
    """One transaction for the audit write-back + terminal status."""
    async with ctx.session_factory() as session:
        await jobs.apply_audit_outcomes(session, updates)
        await jobs.finish_job(session, job_id, status)
        await session.commit()


def _terminal_updates(
    audit_ids: list[uuid.UUID], outcome: str
) -> list[tuple[uuid.UUID, str, str | None]]:
    return [(audit_id, outcome, None) for audit_id in audit_ids]


async def execute_ticket(ticket: QueueTicket, ctx: EngineContext) -> None:
    """Run one dequeued ticket end to end (see module docstring)."""
    job_id = uuid.UUID(ticket.job_id)
    try:
        ops = list(parse_canonical_segments(ticket.canonical_ops))
    except ValueError:
        _logger.error("write job %s: corrupt canonical segments, failing honest", job_id)
        async with ctx.session_factory() as session:
            await jobs.finish_job(session, job_id, "failed")
            await session.commit()
        return
    phash = payload_hash(ticket.student_no, ops)
    stuid = jobs.audit_stuid_hash(ctx.settings.app_secret, ticket.student_no)
    cutoff = ctx.now() - timedelta(seconds=ctx.settings.write_queue_dwell_max)

    async with ctx.session_factory() as session:
        job = await jobs.claim_job(session, job_id, not_older_than=cutoff)
        await session.commit()
    if job is None:
        # Not claimed: superseded/cancelled already (honest no-op), or stale
        # beyond the dwell max -> cancel now with the honest status.
        if await _current_status(ctx, job_id) == "queued":
            async with ctx.session_factory() as session:
                await jobs.finish_job(session, job_id, "cancelled")
                await session.commit()
            _logger.info("write job %s dwell-cancelled (older than WRITE_QUEUE_DWELL_MAX)", job_id)
        return

    try:
        async with ctx.session_factory() as session:
            audit_ids = await jobs.insert_pending_audits(
                session, job_id=job_id, ops=ops, payload_hash=phash, stuid_hash=stuid
            )
            await session.commit()
    except SQLAlchemyError as exc:
        # Fail-closed: the audit sink is down, so the school is NEVER called.
        _logger.error("write job %s: audit pre-insert failed; zero school contact: %r", job_id, exc)
        async with ctx.session_factory() as session:
            await jobs.finish_job(session, job_id, "failed")
            await session.commit()
        return

    jar_payload = await load_selcrs(
        ctx.redis, ticket.session_ref, sliding_ttl=ctx.settings.selcrs_session_ttl_sliding
    )
    if jar_payload is None:
        await _finalize(ctx, job_id, _terminal_updates(audit_ids, OUTCOME_STAGE_EXPIRED), "failed")
        return
    if await _current_status(ctx, job_id) != "running":
        await _finalize(ctx, job_id, _terminal_updates(audit_ids, OUTCOME_SUPERSEDED), "failed")
        return

    jar = deserialize_cookies(jar_payload)
    form_html, _ = await _transport_call(ctx, lambda: get_write_form(jar, ticket.form_url))
    if form_html is None:
        outcome = OUTCOME_TRANSPORT_FAILED
        await _finalize(ctx, job_id, _terminal_updates(audit_ids, outcome), "failed")
        return
    if is_session_bounce(form_html):
        await _finalize(ctx, job_id, _terminal_updates(audit_ids, OUTCOME_STAGE_EXPIRED), "failed")
        return
    hidden = parse_form_hidden_inputs(form_html)
    # The 送出 button's JS pin wins over the form's static action: on the LIVE
    # ssform the static action is the 暫存/draft endpoint (ssform.asp) and the
    # real submit is ssprs.asp; posting to the static action re-renders the
    # form (the 10:04 probe's parse_failed root cause, ssform_live_1151.html).
    action = parse_submit_action(form_html) or parse_form_action(form_html)
    send_value = parse_send_value(form_html)
    if send_value is not None:
        hidden.setdefault(SEND_NAME, send_value)
    try:
        payload = None if action is None else _BUILDERS[ticket.variant](ops, hidden)
    except (ValueError, KeyError):
        payload = None
    if payload is not None:
        # The live form's hidden step is blank; the 送出 click injects the real
        # step (2 at ssform, live-verified). Provisional forms carry their own
        # hidden step and yield no pin, so the replayed value survives there.
        submit_step = parse_submit_step(form_html)
        if submit_step is not None:
            payload["step"] = submit_step
    if payload is None:
        await _finalize(ctx, job_id, _terminal_updates(audit_ids, OUTCOME_PARSE_FAILED), "failed")
        return
    if await _current_status(ctx, job_id) != "running":
        await _finalize(ctx, job_id, _terminal_updates(audit_ids, OUTCOME_SUPERSEDED), "failed")
        return

    submit_url = urljoin(ticket.form_url, action)
    resp_html, post_retried = await _transport_call(
        ctx, lambda: post_write(jar, submit_url, payload, referer=ticket.form_url)
    )
    if resp_html is None:
        await _finalize(ctx, job_id, _terminal_updates(audit_ids, OUTCOME_TRANSPORT_FAILED), "failed")
        return
    try:
        parsed = parse_submit_response(resp_html, [op.code for op in ops])
    except SelcrsSessionExpired:
        await _finalize(ctx, job_id, _terminal_updates(audit_ids, OUTCOME_STAGE_EXPIRED), "failed")
        return

    updates: list[tuple[uuid.UUID, str, str | None]] = []
    for audit_id, op in zip(audit_ids, ops, strict=True):
        verdict = parsed[op.code]
        outcome = verdict.outcome
        if outcome == OUTCOME_FAILED and post_retried and verdict.duplicate_like:
            outcome = OUTCOME_UNKNOWN_RECONCILED
        updates.append((audit_id, outcome, verdict.school_msg))
    if post_retried:
        updates = await reconcile.maybe_reconcile(
            ctx.redis, ctx.settings, ticket, ops, updates
        )
    await _finalize(ctx, job_id, updates, "done")
