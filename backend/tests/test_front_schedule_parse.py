"""Parser tests for the front-page 選課日程 table (fixture: front_live_1151).

The fixture is the REAL, public, personal-data-free front page captured
2026-09-04 (12 rows: 初選一..選課確認, 8 windows + 4 公佈 instants).
"""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.schedule.front import parse_front_schedule
from app.selcrs.errors import SelcrsUnavailable

FIXTURE = Path(__file__).parent / "fixtures" / "front_live_1151.html"
TZ = ZoneInfo("Asia/Taipei")


def _load() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def test_parses_all_twelve_events() -> None:
    schedule = parse_front_schedule(_load(), tz=TZ)
    assert len(schedule.events) == 12
    assert schedule.title == "一佰一十五學年度第一學期選課日程"


def test_first_window_exact_times() -> None:
    schedule = parse_front_schedule(_load(), tz=TZ)
    first = schedule.events[0]
    assert (first.key, first.label, first.kind) == ("first_round_1", "初選一", "window")
    assert first.start == datetime(2026, 8, 20, 9, 0, tzinfo=TZ)
    assert first.end == datetime(2026, 8, 21, 22, 0, tzinfo=TZ)


def test_result_rows_are_instants() -> None:
    schedule = parse_front_schedule(_load(), tz=TZ)
    instants = [event for event in schedule.events if event.kind == "instant"]
    assert [event.key for event in instants] == [
        "first_round_1_result",
        "first_round_2_result",
        "add_drop_1_result",
        "add_drop_2_result",
    ]
    assert all(event.end is None for event in instants)
    assert instants[0].start == datetime(2026, 8, 24, 14, 0, tzinfo=TZ)


def test_withdrawal_window_present() -> None:
    schedule = parse_front_schedule(_load(), tz=TZ)
    withdrawal = next(event for event in schedule.events if event.key == "withdrawal")
    assert withdrawal.label == "棄選時間"
    assert withdrawal.start == datetime(2026, 11, 13, 9, 0, tzinfo=TZ)
    assert withdrawal.end == datetime(2026, 11, 20, 17, 0, tzinfo=TZ)


def test_ordered_and_timezone_aware() -> None:
    schedule = parse_front_schedule(_load(), tz=TZ)
    starts = [event.start for event in schedule.events]
    assert all(event.start.tzinfo is not None for event in schedule.events)
    assert starts[0] < starts[-1]


def test_unknown_label_gets_positional_key() -> None:
    html = """<html><body><table>
    <tr><td colspan=2><blockquote>某某學年度選課日程</blockquote></td></tr>
    <tr><td><div>新階段名稱</div></td><td><div>：115.10.01(09:00)~115.10.02(17:00)</div></td></tr>
    </table></body></html>"""
    schedule = parse_front_schedule(html, tz=TZ)
    assert schedule.events[0].key == "event_1"
    assert schedule.events[0].label == "新階段名稱"


def test_drift_no_heading_raises() -> None:
    with pytest.raises(SelcrsUnavailable):
        parse_front_schedule("<html><body>選課關閉</body></html>", tz=TZ)


def test_drift_heading_without_rows_raises() -> None:
    html = "<html><body><table><tr><td colspan=2>最新選課日程</td></tr></table></body></html>"
    with pytest.raises(SelcrsUnavailable):
        parse_front_schedule(html, tz=TZ)
