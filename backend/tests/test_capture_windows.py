"""Window-table unit tests: inside/outside/boundary, tz conversion, refusal text."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from scripts.capture.windows import (
    TAIPEI,
    active_window,
    next_window,
    refusal_text,
)

UTC = ZoneInfo("UTC")


def _tpe(month: int, day: int, hour: int, minute: int = 0, year: int = 2026) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=TAIPEI)


def test_inside_first_window_generic_moment() -> None:
    # Given the middle of 加退選一
    # When/Then the guard reports that window active
    assert active_window(_tpe(8, 29, 12)).name == "115-1 加退選一"


def test_window_start_is_inclusive() -> None:
    # Boundary: exactly 2026-08-28 09:00 Asia/Taipei is already inside
    assert active_window(_tpe(8, 28, 9, 0)).name == "115-1 加退選一"


def test_window_end_is_exclusive() -> None:
    # Boundary: exactly 2026-08-31 17:00 Asia/Taipei the window is over
    assert active_window(_tpe(8, 31, 17, 0)) is None


def test_minute_before_end_still_inside() -> None:
    assert active_window(_tpe(8, 31, 16, 59)).name == "115-1 加退選一"


def test_minute_before_start_still_outside() -> None:
    assert active_window(_tpe(8, 28, 8, 59)) is None


def test_inside_second_window() -> None:
    assert active_window(_tpe(9, 10, 12)).name == "115-1 加退選二"


def test_between_windows_is_outside() -> None:
    # Gap: 加退選一 ends 08-31 17:00, 加退選二 starts 09-09 09:00
    assert active_window(_tpe(9, 2, 12)) is None


def test_inside_tentative_1152_window() -> None:
    assert active_window(_tpe(2, 10, 12, year=2027)).name == "115-2 初選/加退選 (tentative)"


def test_utc_moment_is_converted_to_taipei() -> None:
    # 2026-08-28 01:30 UTC == 09:30 Asia/Taipei -> inside
    assert active_window(datetime(2026, 8, 28, 1, 30, tzinfo=UTC)) is not None
    # 2026-08-28 00:30 UTC == 08:30 Asia/Taipei -> still outside
    assert active_window(datetime(2026, 8, 28, 0, 30, tzinfo=UTC)) is None


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(TypeError):
        active_window(datetime(2026, 8, 29, 12, 0))


def test_next_window_names_first_upcoming_start() -> None:
    upcoming = next_window(_tpe(8, 27, 21, 0))
    assert upcoming is not None
    assert upcoming.name == "115-1 加退選一"
    assert upcoming.start == _tpe(8, 28, 9, 0)


def test_next_window_during_gap_points_to_second_window() -> None:
    upcoming = next_window(_tpe(9, 2, 12))
    assert upcoming is not None
    assert upcoming.name == "115-1 加退選二"


def test_next_window_none_after_last() -> None:
    assert next_window(datetime(2027, 3, 1, 0, 0, tzinfo=TAIPEI)) is None


def test_refusal_text_names_next_window_start_and_rerun_command() -> None:
    text = refusal_text(_tpe(8, 27, 21, 30))
    assert "2026-08-28 09:00" in text
    assert "115-1 加退選一" in text
    assert "--run" in text


def test_refusal_text_without_future_window_says_so() -> None:
    text = refusal_text(datetime(2027, 3, 1, 0, 0, tzinfo=TAIPEI))
    assert "No further window" in text
