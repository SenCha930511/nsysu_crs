"""Operational accuracy gate for the ddddocr captcha solver (plan todo 5).

Runs ``--pages N`` consecutive LIVE catalog pages through ``CaptchaLoop``
(fresh BMP -> solve -> submit per attempt, at most 5 attempts per page),
logs every attempt's outcome plus the per-attempt success rate p, and
asserts every page cleared within the 5-attempt budget. The report APPENDS
to ``qa/05-accuracy.log`` so later batches accumulate in one evidence file -
the plan's gate needs >=20 pages spread over >=3 distinct time slots.

Usage:
    cd backend && uv run python -m scripts.captcha_gate --pages 7 \
        --label "batch 1/3 (evening 2026-08-27)"

No login is needed: dplycourse.asp is the PUBLIC captcha-parented catalog
endpoint. Pages are independent loop runs (WKDAY filter rotates 1..7 so each
page is a distinct slice); this gate measures CAPTCHA accuracy only - row
and pagination parsing belongs to todo 6 and is deliberately NOT done here.

Exit codes: 0 = every page cleared in <=5 attempts; 1 = at least one page
exhausted the budget (CaptchaUnsolvable - a SOLVER accuracy failure, the
plan's BLOCKED-ON-USER-DECISION input); 3 = batch aborted by a school-side
transport anomaly (SelcrsUnavailable - breaker territory, not solver data).
Per-attempt outcomes are derived from the loop's attempt count: within one
page run the ONLY retry trigger is a wrong-code marker response (transport
anomalies abort the run instead), so attempts 1..k-1 were rejections and the
k-th was the acceptance - no guesswork involved.
"""

import argparse
import importlib.metadata
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final
from zoneinfo import ZoneInfo

import anyio

from app.selcrs.endpoints import CatalogQuery
from app.selcrs.errors import SelcrsUnavailable
from app.solver.errors import CaptchaUnsolvable
from app.solver.loop import MAX_SOLVE_ATTEMPTS, CaptchaLoop

TAIPEI: Final = ZoneInfo("Asia/Taipei")
REPO_ROOT: Final = Path(__file__).resolve().parents[2]
DEFAULT_LOG: Final = REPO_ROOT / "qa" / "05-accuracy.log"
EXIT_UNSOLVABLE: Final = 1
EXIT_SCHOOL_DOWN: Final = 3
WEEKDAYS: Final = ("1", "2", "3", "4", "5", "6", "7")


@dataclass(frozen=True, slots=True)
class PageOutcome:
    """One gated page: attempts spent, whether the school accepted a code."""

    page: int
    weekday: str
    attempts: int
    accepted: bool
    seconds: float


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scripts.captcha_gate",
        description="Todo-5 operational gate: N live catalog pages through the captcha loop.",
    )
    parser.add_argument(
        "--pages", type=int, required=True, help="number of consecutive live pages to gate"
    )
    parser.add_argument(
        "--label",
        default=None,
        help="batch label for the log header (default: timestamp-based)",
    )
    parser.add_argument(
        "--year-sem", default="1151", help="catalog semester code D0 (default: 1151)"
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=DEFAULT_LOG,
        help=f"evidence file to APPEND to (default: {DEFAULT_LOG})",
    )
    return parser


async def run_pages(pages: int, year_sem: str) -> tuple[list[PageOutcome], str | None]:
    """Run pages sequentially through the loop. Returns outcomes plus an
    abort reason if a school-side anomaly cut the batch short."""
    outcomes: list[PageOutcome] = []
    loop = CaptchaLoop()  # real adapter fetchers + real ddddocr solver
    for page in range(1, pages + 1):
        weekday = WEEKDAYS[(page - 1) % len(WEEKDAYS)]
        started = time.monotonic()
        try:
            result = await loop.run_page(
                CatalogQuery(year_sem=year_sem, wkday=weekday)
            )
            outcomes.append(
                PageOutcome(page, weekday, result.attempts, True, time.monotonic() - started)
            )
        except CaptchaUnsolvable as exc:
            outcomes.append(
                PageOutcome(page, weekday, exc.attempts, False, time.monotonic() - started)
            )
        except SelcrsUnavailable as exc:
            return outcomes, f"page {page} (WKDAY={weekday}): SelcrsUnavailable: {exc.detail}"
    return outcomes, None


def render_report(
    outcomes: list[PageOutcome],
    *,
    label: str,
    started: datetime,
    pages_requested: int,
    year_sem: str,
    abort_reason: str | None,
) -> list[str]:
    """Human-readable evidence block (one per batch, appended to the log)."""
    provider = importlib.metadata.version("ddddocr")
    lines = [
        "=" * 80,
        f"captcha gate | {label} | started {started:%Y-%m-%d %H:%M:%S} Asia/Taipei",
        (
            f"cmd: uv run python -m scripts.captcha_gate --pages {pages_requested} | "
            f"provider ddddocr=={provider} (pin evidence: qa/05-pin.log)"
        ),
        (
            "pages are independent loop runs against the PUBLIC catalog (no login): "
            f"dplycourse D0={year_sem}, WKDAY rotating 1..7; captcha accuracy only - "
            "row parsing is todo 6 and is deliberately NOT done here"
        ),
        "-" * 80,
    ]
    for outcome in outcomes:
        if outcome.accepted:
            steps = ", ".join(
                f"attempt {number} rejected (wrong-code marker)"
                for number in range(1, outcome.attempts)
            )
            steps = f"{steps}, " if steps else ""
            verdict = "ok"
        else:
            steps = ", ".join(
                f"attempt {number} rejected (wrong-code marker)"
                for number in range(1, outcome.attempts + 1)
            )
            steps = f"{steps}, " if steps else ""
            verdict = "CAPTCHA-UNSOLVABLE"
        lines.append(
            f"page {outcome.page} (WKDAY={outcome.weekday}): {steps}"
            f"{'ACCEPTED' if outcome.accepted else 'gave up'} -> "
            f"{outcome.attempts} attempts, {outcome.seconds:.1f}s [{verdict}]"
        )
    lines.append("-" * 80)
    if abort_reason is not None:
        lines.append(f"BATCH ABORTED (school-side anomaly, NOT solver data): {abort_reason}")
        return lines
    accepted_pages = [outcome for outcome in outcomes if outcome.accepted]
    total_attempts = sum(outcome.attempts for outcome in outcomes)
    rate = len(accepted_pages) / total_attempts if total_attempts else 0.0
    lines.append(
        f"pages ok: {len(accepted_pages)}/{pages_requested} | "
        f"CaptchaUnsolvable: {len(outcomes) - len(accepted_pages)}"
    )
    lines.append(
        f"attempts: total {total_attempts}, accepted {len(accepted_pages)} "
        f"-> per-attempt success rate p = {rate:.3f} ({rate:.1%})"
    )
    depth = ", ".join(
        f"#{number} "
        f"{sum(1 for outcome in accepted_pages if outcome.attempts == number)}"
        f"/{sum(1 for outcome in outcomes if outcome.attempts >= number)} accepted"
        for number in range(1, MAX_SOLVE_ATTEMPTS + 1)
        if any(outcome.attempts >= number for outcome in outcomes)
    )
    lines.append(f"per-depth accepted/reached: {depth}")
    worst = max(outcomes, key=lambda outcome: outcome.attempts)
    lines.append(f"worst retries-per-page: {worst.attempts} (page {worst.page})")
    passed = len(accepted_pages) == pages_requested
    lines.append(
        f"gate: {'PASS - every page cleared within <=' if passed else 'FAIL - page(s) exhausted the '}"
        f"{MAX_SOLVE_ATTEMPTS}-attempt budget"
    )
    lines.append(f"batch complete {datetime.now(TAIPEI):%Y-%m-%d %H:%M:%S} Asia/Taipei")
    return lines


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.pages < 1:
        build_parser().error("--pages must be >= 1")
    started = datetime.now(TAIPEI)
    label = args.label if args.label is not None else f"batch ({started:%Y-%m-%d %H:%M} Asia/Taipei)"
    outcomes, abort_reason = anyio.run(run_pages, args.pages, args.year_sem)
    lines = render_report(
        outcomes,
        label=label,
        started=started,
        pages_requested=args.pages,
        year_sem=args.year_sem,
        abort_reason=abort_reason,
    )
    text = "\n".join(lines) + "\n"
    args.log.parent.mkdir(parents=True, exist_ok=True)
    with args.log.open("a", encoding="utf-8") as evidence:
        evidence.write(text)  # APPEND: batches 2-3 (other time slots) follow
    sys.stdout.write(text)
    if abort_reason is not None:
        return EXIT_SCHOOL_DOWN
    return 0 if all(outcome.accepted for outcome in outcomes) else EXIT_UNSOLVABLE


if __name__ == "__main__":
    raise SystemExit(main())
