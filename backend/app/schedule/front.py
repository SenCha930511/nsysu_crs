"""Parser for the 選課日程 table on the selcrs front page.

Live markup (front_live_1151 fixture, 2026-09-04): a heading blockquote
carrying 「<semester>學年度第X學期選課日程」, then one ``tr`` per event -
cell 1 holds the label div, cell 2 a spec div shaped either

- window:  ``：115.08.20(09:00)&nbsp;~&nbsp;115.08.21(22:00)``
- instant: ``：115.08.24(14:00)``          (the 公佈 rows)

Years are ROC (民國): ``115`` = 2026, so ``year + 1911``. Labels are kept
VERBATIM from the school - we never rename or fabricate rows; unknown
labels get a positional key, and a page with no schedule markers at all is
shape drift -> SelcrsUnavailable (breaker path), never a guessed answer.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from app.selcrs.errors import SelcrsUnavailable

#: Visible-text anchor proving this is the schedule-bearing page.
_HEADING_MARKER: Final = "選課日程"

#: ``115.08.20(09:00)`` - ROC year (2-3 digits), dot-separated, 24h clock.
_TIMESTAMP_RE: Final = re.compile(
    r"(?P<roc>\d{2,3})\.(?P<month>\d{1,2})\.(?P<day>\d{1,2})\((?P<hour>\d{1,2}):(?P<minute>\d{2})\)"
)

#: Stable keys for the labels the school has actually published (i18n hooks
#: on the frontend; labels remain the display text, keys the stable id).
_LABEL_KEYS: Final = {
    "初選一": "first_round_1",
    "初選一公佈": "first_round_1_result",
    "初選二": "first_round_2",
    "初選二公佈": "first_round_2_result",
    "加退選一": "add_drop_1",
    "加退選一公佈": "add_drop_1_result",
    "加退選二": "add_drop_2",
    "加退選二公佈": "add_drop_2_result",
    "異常處理": "exception",
    "超修單列印": "overload_print",
    "棄選時間": "withdrawal",
    "選課確認": "confirmation",
}


@dataclass(frozen=True, slots=True)
class ScheduleEvent:
    """One schedule row: a window (start..end) or a single instant (公佈)."""

    key: str
    label: str  # verbatim school wording
    kind: Literal["window", "instant"]
    start: datetime  # tz-aware (Asia/Taipei)
    end: datetime | None  # None iff kind == "instant"


@dataclass(frozen=True, slots=True)
class FrontSchedule:
    """The parsed front-page schedule: verbatim title + ordered events."""

    title: str  # e.g. 一佰一十五學年度第一學期選課日程
    events: tuple[ScheduleEvent, ...]


def _parse_timestamp(match: re.Match[str], tz: ZoneInfo) -> datetime:
    return datetime(
        year=int(match["roc"]) + 1911,
        month=int(match["month"]),
        day=int(match["day"]),
        hour=int(match["hour"]),
        minute=int(match["minute"]),
        tzinfo=tz,
    )


def parse_front_schedule(html: str, *, tz: ZoneInfo) -> FrontSchedule:
    """Parse the 選課日程 table out of one decoded front page.

    Raises:
        SelcrsUnavailable: no schedule heading, or a heading with zero
            parseable rows (unrecognized school page shape).
    """
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.find(string=re.compile(_HEADING_MARKER))
    if heading is None:
        raise SelcrsUnavailable("front page carries no 選課日程 heading")
    table = heading.find_parent("table")
    if table is None:
        raise SelcrsUnavailable("選課日程 heading has no surrounding table")
    title = heading.parent.get_text(strip=True) if heading.parent else _HEADING_MARKER

    events: list[ScheduleEvent] = []
    for row in table.find_all("tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) != 2:
            continue  # heading/banner rows use colspan; never guess columns
        label = cells[0].get_text(strip=True).replace(" ", "")
        if not label or _HEADING_MARKER in label:
            continue
        stamps = list(_TIMESTAMP_RE.finditer(cells[1].get_text()))
        if not stamps:
            continue  # prose row inside the schedule table: skip, don't invent
        start = _parse_timestamp(stamps[0], tz)
        end = _parse_timestamp(stamps[1], tz) if len(stamps) > 1 else None
        if end is not None and end <= start:
            continue  # nonsense window: drift, not data
        events.append(
            ScheduleEvent(
                key=_LABEL_KEYS.get(label, f"event_{len(events) + 1}"),
                label=label,
                kind="window" if end is not None else "instant",
                start=start,
                end=end,
            )
        )
    if not events:
        raise SelcrsUnavailable("選課日程 table parsed to zero events")
    return FrontSchedule(title=title, events=tuple(events))
