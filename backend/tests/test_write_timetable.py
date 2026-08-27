"""Server timetable-rule tests (plan todo 14 check 4 mirror of todo 10).

Same rule/pins as the shipped frontend vitest (conflicts.test.ts): "56" vs
"5B" clashes, "A" vs "1" does not, unknown codes throw. Plus the fused
slt_result 教室 string -> 7-slot conversion used for selection clash targets.
"""

import pytest

from app.write.timetable import (
    UnknownPeriodCodeError,
    days_from_fused,
    is_conflict_days,
    parse_day_string,
)

EMPTY_WEEK = ("", "", "", "", "", "", "")


def _week(day: int, periods: str) -> tuple[str, ...]:
    days = list(EMPTY_WEEK)
    days[day] = periods
    return tuple(days)


def test_same_day_shared_period_conflicts():
    # "56" vs "5B" on the same day share period 5 (todo-10 vitest pin)
    assert is_conflict_days(_week(2, "56"), _week(2, "5B")) is True


def test_same_day_disjoint_periods_do_not_conflict():
    # "A" vs "1" on the same day share nothing (todo-10 vitest pin)
    assert is_conflict_days(_week(2, "A"), _week(2, "1")) is False


def test_same_periods_on_different_days_never_conflict():
    assert is_conflict_days(_week(0, "34"), _week(4, "34")) is False
    # Empty/short weeks compare clean
    assert is_conflict_days(EMPTY_WEEK, ("34",)) is False


def test_unknown_period_code_fails_loudly():
    with pytest.raises(UnknownPeriodCodeError):
        parse_day_string("3Z")
    with pytest.raises(UnknownPeriodCodeError):
        is_conflict_days(_week(0, "?"), _week(0, "3"))


def test_days_from_fused_real_shape():
    assert days_from_fused("三2,3,4") == ("", "", "234", "", "", "", "")
    assert days_from_fused("五6") == ("", "", "", "", "6", "", "")
    # full-width comma + lowercase period tolerated (selections fused regex)
    assert days_from_fused("一b,c") == ("BC", "", "", "", "", "", "")


def test_days_from_fused_unfused_shapes_yield_none():
    assert days_from_fused(None) is None
    assert days_from_fused("") is None
    assert days_from_fused("工EC 5012") is None
    assert days_from_fused("未定") is None
