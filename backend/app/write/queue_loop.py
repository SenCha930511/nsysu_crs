"""Write-queue consumer loop + dwell sweep (plan todo 15).

The loop is the SINGLE consumer of the writeq FIFO: jobs execute one at a
time, which makes per-student execution serial by construction (the global
<=2 school concurrency lives in the adapter semaphore, not here). The sweep
dwell-cancels queued/running jobs older than WRITE_QUEUE_DWELL_MAX - also
the honest terminal for a job whose Redis ticket was lost (Redis is pinned
noeviction; loss means instance failure, never silent eviction).
"""

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta

from app.write import jobs
from app.write.engine import EngineContext, execute_ticket
from app.write.queue import parse_ticket

_logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SweepReport:
    cancelled: int


async def sweep_once(ctx: EngineContext) -> SweepReport:
    """Dwell guard: stale queued/running jobs -> cancelled (honest status)."""
    cutoff = ctx.now() - timedelta(seconds=ctx.settings.write_queue_dwell_max)
    async with ctx.session_factory() as session:
        cancelled = await jobs.cancel_stale_active_jobs(session, older_than=cutoff)
        await session.commit()
    return SweepReport(cancelled)


async def write_queue_loop(
    ctx: EngineContext,
    *,
    pop: Callable[[], Awaitable[str | None]],
    sweep_interval: float = 30.0,
    log: Callable[[str], None] | None = None,
) -> None:
    """Pop-and-execute forever. A crashing job is logged and abandoned - the
    dwell sweep reaps its 'running' row honestly instead of killing the
    consumer (the plan's crash semantics: at most a bounded dwell delay)."""
    emit = log if log is not None else (lambda message: _logger.info("%s", message))
    next_sweep = 0.0
    while True:
        raw = await pop()
        if raw is not None:
            ticket = parse_ticket(raw)
            if ticket is None:
                emit("discarding a corrupt write-queue ticket")
            else:
                try:
                    await execute_ticket(ticket, ctx)
                except Exception:
                    _logger.exception("write ticket for job %s crashed", ticket.job_id)
        moment = time.monotonic()
        if moment >= next_sweep:
            report = await sweep_once(ctx)
            if report.cancelled:
                emit(f"write dwell guard cancelled {report.cancelled} stale job(s)")
            next_sweep = moment + sweep_interval
