"""Server-side timetable rule for write preview (plan todo 14 check 4).

Adapted from NSYSU-OpenDev/NSYSUSelectorHelper (MIT License,
Copyright (c) Cellery Lin and whats2000):
    client-website/src/components/SelectorSetting.tsx (isConflict)
    https://github.com/NSYSU-OpenDev/NSYSUSelectorHelper

This is the exact server mirror of the shipped todo-10 frontend rule
(frontend/src/lib/conflicts.ts + config/timeslots.ts): ``class_time`` is 7
slots Monday..Sunday, each a string of single-char period codes ("56" =
periods 5 and 6); two courses clash iff on ANY weekday their period strings
share at least one code (per-day char-set intersection). "56" vs "5B"
conflicts (period 5); "A" vs "1" does not; same periods on different days
never conflict.

Unknown period codes FAIL LOUDLY (UnknownPeriodCodeError), never silently:
a dropped code would hide a class from conflict detection. The alphabet is
already bounded by our own dplycourse ingest (day cells are nbsp-trimmed
period-code strings), so a raise here means corrupt catalog data - the same
systemic condition the frontend treats as a render-stopping bug.

days_from_fused converts slt_result's fused 教室 time string ("三2,3,4") -
the only timetable shape the selections snapshot carries for unknown-join
rows - into the same 7-slot form, so selection-vs-add clashes ride ONE rule.
"""

import re
from collections.abc import Sequence
from typing import Final

#: The 15 valid period codes (todo-10 TIMESLOTS, chronological).
PERIOD_CODES: Final = frozenset("A1234B56789CDEF")

_DAY_TO_INDEX: Final = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6}

#: Whole fused-cell shape from slt_result 教室 ("三2,3,4"): one weekday + a
#: comma-separated period run (half/full-width commas tolerated, as upstream).
_FUSED_TIME: Final = re.compile(r"^([一二三四五六日])([0-9A-Ea-e,，]+)$")


class UnknownPeriodCodeError(ValueError):
    """A class_time char outside the 15 known period codes."""

    def __init__(self, code: str) -> None:
        super().__init__(f"Unknown period code: {code!r}")
        self.code = code


def parse_day_string(raw: str) -> frozenset[str]:
    """One day slot ("56") -> validated period-code set; raises on unknown."""
    codes = set()
    for ch in raw:
        if ch.upper() not in PERIOD_CODES:
            raise UnknownPeriodCodeError(ch)
        codes.add(ch.upper())
    return frozenset(codes)


def _slot(class_time: Sequence[str], day: int) -> str:
    return class_time[day] if day < len(class_time) else ""


def is_conflict_days(a: Sequence[str], b: Sequence[str]) -> bool:
    """Per-day char-set intersection over two 7-slot class_time arrays.

    Slots beyond index 6 are never read; missing trailing slots read as "".
    """
    for day in range(7):
        codes_a = parse_day_string(_slot(a, day))
        if not codes_a:
            continue
        if codes_a & parse_day_string(_slot(b, day)):
            return True
    return False


def days_from_fused(times: str | None) -> tuple[str, ...] | None:
    """Fused slt_result day ("三2,3,4") -> 7-slot class_time, else None.

    None means the cell never matched the fused shape (unparseable foreign
    text) - the caller then has no timetable for that selection and conflict
    detection simply cannot prove a clash against it (honest non-answer, not
    a fabricated free pass: such rows sit in the response for the user).
    """
    if not times:
        return None
    match = _FUSED_TIME.match(times.strip())
    if match is None:
        return None
    periods = parse_day_string("".join(ch for ch in match.group(2) if ch not in ",，"))
    days = [""] * 7
    days[_DAY_TO_INDEX[match.group(1)]] = "".join(sorted(periods))
    return tuple(days)
