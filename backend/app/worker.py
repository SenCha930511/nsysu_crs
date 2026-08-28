"""Background worker entrypoint: catalog scheduler + write-queue engine.

Two loops under one anyio task group:

- the catalog ingest cron loop (todo 6: off/peak crons, Redis singleton
  lock, coalesced ticks), unchanged;
- the write-submission engine (todo 15): the SINGLE consumer of the
  ``writeq:jobs`` FIFO, so per-student execution is serial by construction
  and the adapter's process-wide semaphore keeps global school concurrency
  at <=2. BRPOP doubles as the sweep timer's wake-up (2s timeout; dwell
  guard runs every 30s and once at startup).

Crash semantics (plan): a dead worker releases nothing - the ingest lock
expires at its EX and queued write jobs either still hold their Redis
ticket (the next worker pops them) or were reaped honestly by the dwell
guard. Redis being down lets this process raise and rely on the compose
restart policy, exactly like the catalog loop before it.
"""

import logging
from collections.abc import Awaitable
from typing import Protocol, cast

import anyio
import redis.asyncio as aioredis

from app.auth.redis_iface import AuthRedis
from app.catalog.ingest import run_ingest
from app.catalog.schedule import RedisLockClient, scheduler_loop
from app.config import Settings
from app.db import build_engine, build_session_factory
from app.write.engine import EngineContext
from app.write.queue import WRITE_QUEUE_KEY
from app.write.queue_loop import write_queue_loop

logger = logging.getLogger(__name__)

_BRPOP_TIMEOUT_SECONDS = 2
_SWEEP_INTERVAL_SECONDS = 30.0


async def _run() -> None:
    # app_secret is populated from env by pydantic-settings (see app.main).
    settings = Settings()  # type: ignore[call-arg]
    engine = build_engine(settings)
    session_factory = build_session_factory(engine)
    class _WorkerRedis(AuthRedis, RedisLockClient, Protocol):
        """The auth + lock protocol union this one shared client must satisfy.

        The cast below is deliberate and single: redis-py's stubs don't
        specialize on ``decode_responses=True`` (values stay ``bytes | str``)
        while every value in this deployment is a str — both member protocols
        are documented for exactly that client."""

        def brpop(
            self, keys: list[str], timeout: int = 0
        ) -> Awaitable[tuple[str, str] | None]: ...

        def aclose(self) -> Awaitable[None]: ...

    redis = cast(
        _WorkerRedis,
        aioredis.Redis.from_url(settings.redis_url, decode_responses=True),
    )

    async def _ingest_once() -> object:
        return await run_ingest(session_factory)

    ctx = EngineContext(redis=redis, session_factory=session_factory, settings=settings)

    async def _pop_ticket() -> str | None:
        popped = await redis.brpop([WRITE_QUEUE_KEY], timeout=_BRPOP_TIMEOUT_SECONDS)
        if popped is None:
            return None
        # redis-py returns (key, value); decode_responses=True -> str value.
        return str(popped[1])

    logger.info(
        "worker started: semester=%s, catalog crons offpeak=%r peak=%r peak_dates=%r, "
        "write queue=%s dwell_max=%ss",
        settings.semester_year_sem,
        settings.catalog_cron_offpeak,
        settings.catalog_cron_peak,
        settings.catalog_peak_dates or "(none)",
        WRITE_QUEUE_KEY,
        settings.write_queue_dwell_max,
    )
    try:
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(
                lambda: scheduler_loop(
                    settings,
                    redis=redis,
                    run_once=_ingest_once,
                    log=lambda message: logger.info("%s", message),
                )
            )
            task_group.start_soon(
                lambda: write_queue_loop(
                    ctx,
                    pop=_pop_ticket,
                    sweep_interval=_SWEEP_INTERVAL_SECONDS,
                    log=lambda message: logger.info("%s", message),
                )
            )
    finally:
        await redis.aclose()
        await engine.dispose()


def main() -> None:
    """Console entry: configure logging and run the async loops."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    anyio.run(_run)


if __name__ == "__main__":
    main()
