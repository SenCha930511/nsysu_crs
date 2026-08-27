"""Todo-4 live-capture kit: fixtures, probes, verified facts (user-assisted).

Runnable as ``cd backend && uv run python -m scripts.capture``:

- ``--check-window`` (default): consult the window table; print which window
  the current Asia/Taipei moment falls in, or print the refusal (next window
  start included) and exit 2. The refusal is also written to
  ``qa/04-not-in-window.log``.
- ``--run``: same guard first; only inside a window this drops into the
  interactive capture protocol in ``kit.py`` (builds fixtures and probes
  against the LIVE school host with the user's credentials, memory only).
"""

import argparse
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Final

from scripts.capture.windows import (
    TAIPEI,
    SelectionWindow,
    active_window,
    refusal_text,
)

REPO_ROOT: Final = Path(__file__).resolve().parents[3]
DEFAULT_QA_DIR: Final = REPO_ROOT / "qa"
NOT_IN_WINDOW_LOG: Final = "04-not-in-window.log"
EXIT_NOT_IN_WINDOW: Final = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scripts.capture",
        description="Todo-4 live capture kit (window-guarded).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check-window",
        dest="run",
        action="store_false",
        help="only report the window status (default)",
    )
    mode.add_argument(
        "--run",
        dest="run",
        action="store_true",
        help="run the interactive capture protocol (only inside a window)",
    )
    parser.set_defaults(run=False)
    return parser


def main(
    argv: list[str] | None = None,
    *,
    now: datetime | None = None,
    qa_dir: Path | None = None,
    run_impl: Callable[[SelectionWindow], int] | None = None,
) -> int:
    """CLI entry. Seams (``now``/``qa_dir``/``run_impl``) exist for tests."""
    args = build_parser().parse_args(argv)
    moment = now if now is not None else datetime.now(TAIPEI)
    window = active_window(moment)
    if window is None:
        text = refusal_text(moment)
        print(text)
        log_dir = qa_dir if qa_dir is not None else DEFAULT_QA_DIR
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / NOT_IN_WINDOW_LOG
        log_path.write_text(text + "\n", encoding="utf-8")
        print(f"(refusal also written to {log_path})", file=sys.stderr)
        return EXIT_NOT_IN_WINDOW
    if not args.run:
        print(
            f"Inside window: {window.name} "
            f"({window.start:%Y-%m-%d %H:%M} -> {window.end:%Y-%m-%d %H:%M} Asia/Taipei)."
        )
        print("Live capture available: cd backend && uv run python -m scripts.capture --run")
        return 0
    runner = run_impl if run_impl is not None else _run_capture_kit
    return runner(window)


def _run_capture_kit(window: SelectionWindow) -> int:
    import anyio

    from scripts.capture import kit

    return anyio.run(kit.run_capture, window)


if __name__ == "__main__":
    raise SystemExit(main())
