"""CLI behaviour: refusal path (exit 2 + log file) and --run guard wiring."""

from datetime import datetime
from pathlib import Path

from scripts.capture.__main__ import EXIT_NOT_IN_WINDOW, main
from scripts.capture.windows import TAIPEI

OUTSIDE = datetime(2026, 8, 27, 21, 0, tzinfo=TAIPEI)
INSIDE = datetime(2026, 8, 28, 10, 0, tzinfo=TAIPEI)


def test_check_window_outside_refuses_exit2_and_writes_log(tmp_path, capsys) -> None:
    # Given a moment outside every window
    # When checking the window
    code = main(["--check-window"], now=OUTSIDE, qa_dir=tmp_path)

    # Then the refusal is printed, logged to 04-not-in-window.log, exit 2
    assert code == EXIT_NOT_IN_WINDOW
    out = capsys.readouterr().out
    assert "Refusing" in out
    assert "2026-08-28 09:00" in out
    log = tmp_path / "04-not-in-window.log"
    assert log.is_file()
    text = log.read_text(encoding="utf-8")
    assert "Refusing" in text
    assert "2026-08-28 09:00" in text


def test_check_window_inside_reports_window_exit0_and_no_log(tmp_path, capsys) -> None:
    code = main(["--check-window"], now=INSIDE, qa_dir=tmp_path)

    assert code == 0
    assert "115-1 加退選一" in capsys.readouterr().out
    assert not (tmp_path / "04-not-in-window.log").exists()


def test_run_outside_still_refuses_and_never_calls_runner(tmp_path) -> None:
    called: list[object] = []

    def runner(window: object) -> int:
        called.append(window)
        return 0

    code = main(["--run"], now=OUTSIDE, qa_dir=tmp_path, run_impl=runner)

    assert code == EXIT_NOT_IN_WINDOW
    assert called == []
    assert (tmp_path / "04-not-in-window.log").exists()


def test_run_inside_dispatches_to_runner(tmp_path) -> None:
    called: list[object] = []

    def runner(window: object) -> int:
        called.append(window)
        return 0

    code = main(["--run"], now=INSIDE, qa_dir=tmp_path, run_impl=runner)

    assert code == 0
    assert len(called) == 1
    assert getattr(called[0], "name") == "115-1 加退選一"


def test_default_args_use_real_now(tmp_path) -> None:
    # Given no time override (CLI resolves real wall time)
    # When checking the window
    # Then it does not raise and returns one of the two valid exit codes (the
    # specific code depends on the wall clock, which the test cannot know)
    code = main(["--check-window"], qa_dir=Path(tmp_path))
    assert code in (0, EXIT_NOT_IN_WINDOW)
