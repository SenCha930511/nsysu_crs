"""Background worker entrypoint (plan todo 6: catalog scheduler).

Owns the catalog ingest cron loop (off-peak / peak with date gating, Redis
singleton lock, coalesced ticks). The write-submission engine (todo 15) will
join this process later. Crash semantics: a dead worker releases nothing -
the ingest lock expires at its EX (<= 2x interval) and the NEXT container
tick resumes; at most one interval is skipped, an accepted degradation per
the plan.
"""

import logging

import anyio
import redis.asyncio as aioredis

from app.catalog.ingest import run_ingest
from app.catalog.schedule import scheduler_loop
from app.config import Settings
from app.db import build_engine, build_session_factory

logger = logging.getLogger(__name__)


async def _run() -> None:
    settings = Settings()
    engine = build_engine(settings)
    session_factory = build_session_factory(engine)
    redis = aioredis.Redis.from_url(settings.redis_url, decode_responses=True)

    async def _ingest_once() -> object:
        return await run_ingest(session_factory)

    logger.info(
        "worker started: semester=%s, catalog crons offpeak=%r peak=%r peak_dates=%r",
        settings.semester_year_sem,
        settings.catalog_cron_offpeak,
        settings.catalog_cron_peak,
        settings.catalog_peak_dates or "(none)",
    )
    try:
        await scheduler_loop(
            settings,
            redis=redis,
            run_once=_ingest_once,
            log=lambda message: logger.info("%s", message),
        )
    finally:
        await redis.aclose()
        await engine.dispose()


def main() -> None:
    """Console entry: configure logging and run the async loop."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    anyio.run(_run)


if __name__ == "__main__":
    main()
