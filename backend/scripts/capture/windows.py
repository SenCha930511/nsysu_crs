"""115 academic-year course-selection window table (todo 4 window guard).

Single source of truth for "may live-capture run right now". The school only
serves the real write forms (ssform/stage5) while a selection window is open,
so any attempt to record fixtures outside one is pointless AND wastes school
resources; callers must refuse with the next window's start instead.

Semester of truth is Asia/Taipei wall time. Windows are start-inclusive /
end-exclusive: at 2026-08-31 17:00:00 the first add/drop window is over.

Dates per plan Verification strategy + task contract:
  115-1 add/drop 1: 2026-08-28 09:00 -> 2026-08-31 17:00
  115-1 add/drop 2: 2026-09-09 09:00 -> 2026-09-11 22:00
  115-2 first-round/add-drop (TENTATIVE, school calendar not yet published):
  2027-01-29 -> 2027-02-25. Day-precision input; times mirror the school's
  usual 09:00 open. Refine on official announcement.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Final
from zoneinfo import ZoneInfo

TAIPEI: Final = ZoneInfo("Asia/Taipei")


@dataclass(frozen=True, slots=True)
class SelectionWindow:
    """One selection window in Asia/Taipei wall time. [start, end)."""

    name: str
    start: datetime
    end: datetime


WINDOWS: Final = (
    SelectionWindow(
        "115-1 加退選一",
        datetime(2026, 8, 28, 9, 0, tzinfo=TAIPEI),
        datetime(2026, 8, 31, 17, 0, tzinfo=TAIPEI),
    ),
    SelectionWindow(
        "115-1 加退選二",
        datetime(2026, 9, 9, 9, 0, tzinfo=TAIPEI),
        datetime(2026, 9, 11, 22, 0, tzinfo=TAIPEI),
    ),
    SelectionWindow(
        "115-2 初選/加退選 (tentative)",
        datetime(2027, 1, 29, 9, 0, tzinfo=TAIPEI),
        datetime(2027, 2, 25, 17, 0, tzinfo=TAIPEI),
    ),
)


def _require_aware(now: datetime) -> None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise TypeError("now must be timezone-aware (naive datetimes are ambiguous)")


def active_window(now: datetime) -> SelectionWindow | None:
    """The window containing ``now`` (start-inclusive, end-exclusive), or None."""
    _require_aware(now)
    for window in WINDOWS:
        if window.start <= now < window.end:
            return window
    return None


def next_window(now: datetime) -> SelectionWindow | None:
    """The earliest window starting strictly after ``now``, or None."""
    _require_aware(now)
    future = [window for window in WINDOWS if window.start > now]
    return min(future, key=lambda window: window.start) if future else None


def refusal_text(now: datetime) -> str:
    """Human-readable refusal for out-of-window runs, naming the next start."""
    _require_aware(now)
    now_tpe = now.astimezone(TAIPEI)
    lines = [
        "[WINDOW-GUARD] Refusing: not inside a course-selection window.",
        f"Now (Asia/Taipei): {now_tpe:%Y-%m-%d %H:%M:%S} ({now_tpe:%a})",
        (
            "Live capture is only possible during an active selection window "
            "(the school only serves the real write forms then)."
        ),
    ]
    upcoming = next_window(now)
    if upcoming is None:
        lines.append("No further window is present in the window table.")
    else:
        lines.append(
            f"Next window: {upcoming.name} - starts "
            f"{upcoming.start:%Y-%m-%d %H:%M} (Asia/Taipei), "
            f"ends {upcoming.end:%Y-%m-%d %H:%M} (Asia/Taipei)."
        )
    lines.append(
        "When the window opens, run: cd backend && uv run python -m scripts.capture --run"
    )
    return "\n".join(lines)
