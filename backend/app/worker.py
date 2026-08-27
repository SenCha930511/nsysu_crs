"""Background worker entrypoint (placeholder).

Catalog ingest (todo 6) and the write-submission engine (todo 15) will live
here; for now the process validates settings and idles so the compose service
contract (app, worker, postgres, redis, caddy) is complete.
"""

import logging

import anyio

from app.config import Settings

logger = logging.getLogger(__name__)


async def _run() -> None:
    settings = Settings()
    logger.info(
        "worker started (placeholder; semester=%s, first_round_write=%s)",
        settings.semester_year_sem,
        settings.feature_first_round_write,
    )
    await anyio.sleep_forever()


def main() -> None:
    """Console entry: configure logging and run the async loop."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    anyio.run(_run)


if __name__ == "__main__":
    main()
