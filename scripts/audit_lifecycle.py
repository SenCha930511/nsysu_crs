#!/usr/bin/env python3
"""write_audit PII lifecycle runner (plan todo 15).

Hot 90 days -> de-identified gzip archive (stuid_hash kept hashed,
school_msg excerpt only) + write_audit_archive_meta row + hot-row deletion
-> archive files deleted after 1 further year (meta marked
``deleted_after_1y``).

Default mode is DRY-RUN (reports counts, writes nothing); pass ``--apply``
to execute. Against the compose stack (DB not host-published):

    docker compose -f deploy/docker-compose.yml run --rm --no-deps \
      -v "$PWD/backend:/app" -v /app/.venv \
      -v "$PWD:/repo" worker \
      uv run --no-sync python /repo/scripts/audit_lifecycle.py \
      --archive-dir /repo/archives/write_audit --apply

(host-run with an explicit --db-url works the same; run it from the repo
root so the sys.path shim below resolves.)
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

import anyio  # noqa: E402

from app.config import Settings  # noqa: E402
from app.db import build_engine, build_session_factory  # noqa: E402
from app.write.audit_lifecycle import report_lines, run_lifecycle  # noqa: E402


async def _run(args: argparse.Namespace) -> int:
    settings = Settings(database_url=args.db_url) if args.db_url else Settings()
    engine = build_engine(settings)
    factory = build_session_factory(engine)
    try:
        async with factory() as session:
            report = await run_lifecycle(
                session,
                archive_dir=args.archive_dir,
                hot_days=args.hot_days,
                archive_days=args.archive_days,
                dry_run=not args.apply,
            )
        for line in report_lines(report):
            print(line)
    finally:
        await engine.dispose()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="write_audit PII lifecycle (hot -> redacted gz -> delete)."
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="database URL (default: DATABASE_URL from the environment/.env)",
    )
    parser.add_argument(
        "--archive-dir",
        type=Path,
        default=REPO_ROOT / "archives" / "write_audit",
        help="archive directory (default: <repo>/archives/write_audit)",
    )
    parser.add_argument("--hot-days", type=int, default=90, help="hot retention (90d)")
    parser.add_argument(
        "--archive-days", type=int, default=365, help="archive retention (1y)"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually archive/delete (default is dry-run: report only)",
    )
    args = parser.parse_args()
    return anyio.run(_run, args)


if __name__ == "__main__":
    raise SystemExit(main())
