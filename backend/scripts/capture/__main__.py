"""Todo-4 live-capture kit: fixtures, probes, verified facts (user-assisted).

Runnable as ``cd backend && uv run python -m scripts.capture``:

- ``--check-window`` (default): consult the window table; print which window
  the current Asia/Taipei moment falls in, or print the refusal (next window
  start included) and exit 2. The refusal is also written to
  ``qa/04-not-in-window.log``.
- ``--run``: same guard first; only inside a window this drops into the
  interactive capture protocol in ``kit.py`` (builds fixtures and probes
  against the LIVE school host with the user's credentials, memory only).
- ``--run-readonly``: NO window guard (allowed anytime). Runs the strictly
  read-only verification round in ``readonly.py``: SSO2 logins + pure GET
  reads only - never an add/drop write of any kind.
- ``--creds-env PATH``: read ``STUDENT_ID``/``SPASSWORD`` from an out-of-band
  env file (must live outside the repo and be owner-readable only, e.g.
  chmod 600) instead of the interactive getpass prompts, which remain the
  default when the flag is absent. The student id is masked as
  ``M153****24`` in all stdout/logs; the password is never printed.
"""

import argparse
import sys
from collections.abc import Callable
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Final

from scripts.capture.creds import Credentials, CredentialsRejected, load_credentials
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
EXIT_CREDS_REJECTED: Final = 4


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scripts.capture",
        description="Todo-4 live capture kit (window-guarded) + read-only round.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check-window",
        dest="mode",
        action="store_const",
        const="check",
        help="only report the window status (default)",
    )
    mode.add_argument(
        "--run",
        dest="mode",
        action="store_const",
        const="run",
        help="run the interactive capture protocol (only inside a window)",
    )
    mode.add_argument(
        "--run-readonly",
        dest="mode",
        action="store_const",
        const="readonly",
        help="run the strictly read-only live round (NO window guard; SSO2 "
        "login POSTs + pure GET reads only - no add/drop writes)",
    )
    parser.add_argument(
        "--creds-env",
        type=Path,
        default=None,
        metavar="PATH",
        help="read STUDENT_ID/SPASSWORD from an out-of-band env file (outside "
        "the repo, owner-only permissions) instead of interactive prompts",
    )
    parser.set_defaults(mode="check")
    return parser


def main(
    argv: list[str] | None = None,
    *,
    now: datetime | None = None,
    qa_dir: Path | None = None,
    run_impl: Callable[[SelectionWindow], int] | None = None,
    readonly_impl: Callable[[Credentials | None], int] | None = None,
) -> int:
    """CLI entry. Seams (``now``/``qa_dir``/``*_impl``) exist for tests."""
    args = build_parser().parse_args(argv)
    creds: Credentials | None = None
    if args.creds_env is not None:
        try:
            creds = load_credentials(Path(args.creds_env), repo_root=REPO_ROOT)
        except CredentialsRejected as exc:
            print(f"[CREDS] Refusing: {exc}", file=sys.stderr)
            return EXIT_CREDS_REJECTED
    if args.mode == "readonly":
        runner = readonly_impl if readonly_impl is not None else _run_readonly_capture
        return runner(creds)
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
    if args.mode == "check":
        print(
            f"Inside window: {window.name} "
            f"({window.start:%Y-%m-%d %H:%M} -> {window.end:%Y-%m-%d %H:%M} Asia/Taipei)."
        )
        print("Live capture available: cd backend && uv run python -m scripts.capture --run")
        return 0
    if creds is not None and run_impl is None:
        return _run_capture_kit_with_creds(window, creds)
    runner = run_impl if run_impl is not None else _run_capture_kit
    return runner(window)


def _run_capture_kit(window: SelectionWindow) -> int:
    import anyio

    from scripts.capture import kit

    return anyio.run(kit.run_capture, window)


def _run_capture_kit_with_creds(window: SelectionWindow, creds: Credentials) -> int:
    import anyio

    from scripts.capture import kit

    return anyio.run(partial(kit.run_capture, window, creds=creds))


def _run_readonly_capture(creds: Credentials | None) -> int:
    import anyio

    from scripts.capture import readonly

    return anyio.run(partial(readonly.run_readonly, creds=creds))


if __name__ == "__main__":
    raise SystemExit(main())
