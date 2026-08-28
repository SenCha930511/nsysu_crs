"""RFC5545 .ics export for one plan (plan todo 12, Wave B).

Contract (plan todo 12 References / todo 6 degraded-identity rule):

- One ``VEVENT`` per course per WEEKDAY-with-periods (multiple days are NEVER
  merged into one event - weekday-recurrence would need them identical).
- ``DTSTART``/``DTEND`` are Asia/Taipei local wall times carrying
  ``TZID=Asia/Taipei``, taking the earliest start / latest end of that day's
  period block; the date is the first such weekday on or after
  ``SEMESTER_START_DATE``.
- The calendar contains exactly one ``VTIMEZONE`` for Asia/Taipei (+08:00,
  no DST). Modern Asia/Taipei has no daylight-saving shifts, so a single
  STANDARD block covers every export horizon we care about; the historical
  rules are deliberately omitted rather than approximated.
- ``RRULE:FREQ=WEEKLY;UNTIL=...`` where UNTIL is
  ``SEMESTER_END_DATE 23:59:59+08:00`` converted to a UTC DATE-TIME (the
  ``...Z`` form RFC5545 requires for date-time UNTIL values).
- ``UID = sha1(year_sem|<code OR degraded identity>|weekday|period-block)
  @nsysu-course-wrapper`` - deterministic against server COURSE rows (school
  code, never the internal PK), so re-ingestion and re-import never duplicate
  calendar entries. Degraded identity (todo 6 spec, used when
  ``courses.code`` is NULL): ``dept|name_zh|teacher|room|class_time``.
- ``DTSTAMP`` is a fixed function of the semester contract (start-of-semester
  in UTC), so two generations of the same input are byte-identical.
- ``LOCATION`` comes from ``courses.room``; ``SUMMARY`` is
  ``name（teacher）`` (name_zh with name_en/code fallback).
- icalendar handles RFC5545 text escaping (``\\ ; , \\n``), 75-octet line
  folding, and CRLF line endings; the API roundtrip tests pin all three.

Loud failure: an unknown period code anywhere in ``class_time`` raises
:class:`IcsBuildError`; a corrupt catalog row must never be silently skipped
into a partial timetable (same rule as the frontend grid).
"""

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Final
from zoneinfo import ZoneInfo

from icalendar import Calendar, Event, Timezone, TimezoneStandard
from icalendar.prop import vRecur

from app.config import Settings
from app.export.timeslots import PERIOD_RANGES
from app.models.courses import Course

UID_DOMAIN: Final = "nsysu-course-wrapper"
TAIPEI_TZID: Final = "Asia/Taipei"

# icalendar needs a zoneinfo for TZID-carrying local datetimes; Asia/Taipei
# has no DST within any semester horizon this app serves.
_TAIPEI: Final = ZoneInfo(TAIPEI_TZID)


class IcsBuildError(ValueError):
    """Unknown period code in catalog data (todo 12 bad-input loudness).

    ``course_label``/``day_index``/``slot`` let the API layer name the
    offending course and the exact raw day slot for the user-facing message.
    """

    def __init__(self, course_label: str, day_index: int, slot: str) -> None:
        self.course_label = course_label
        self.day_index = day_index
        self.slot = slot
        super().__init__(
            f"unknown period code in class_time[{day_index}]={slot!r} "
            f"(course {course_label})"
        )


@dataclass(frozen=True)
class BuiltIcs:
    """One serialized calendar. ``event_count`` feeds the API's empty-plan
    guard (a friendly 409, never an empty/corrupt file)."""

    content: bytes
    event_count: int


def _display_name(course: Course) -> str:
    return (course.name_zh or course.name_en or course.code or "課程").strip()


def course_label(course: Course) -> str:
    """Human-readable identity for error/label text (name + code)."""
    name = _display_name(course)
    return f"{name}（{course.code}）" if course.code else name


def _summary(course: Course) -> str:
    name = _display_name(course)
    teacher = (course.teacher or "").strip()
    return f"{name}（{teacher}）" if teacher else name


def _identity(course: Course) -> str:
    """The UID identity slot: school course code, else the todo-6 degraded
    identity ``dept|name_zh|teacher|room|class_time`` (NULLs as empty)."""
    if course.code:
        return course.code
    class_time = ";".join(course.class_time or [])
    return "|".join(
        [
            course.dept or "",
            course.name_zh or "",
            course.teacher or "",
            course.room or "",
            class_time,
        ]
    )


def event_uid(course: Course, weekday: int, block: str) -> str:
    """``sha1(year_sem|<identity>|<weekday 1-7>|<period-block>)@domain``.
    Deterministic on server rows; survives re-ingestion (internal PK never
    participates) and identical inputs regen to the identical UID."""
    identity = _identity(course)
    material = f"{course.year_sem}|{identity}|{weekday}|{block}"
    return f"{hashlib.sha1(material.encode('utf-8')).hexdigest()}@{UID_DOMAIN}"


def _day_blocks(course: Course) -> list[tuple[int, str, time, time]]:
    """(day_index, canonical block, start, end) per weekday WITH periods.

    Validates EVERY character of every non-empty day slot against the
    period table: an unknown code raises :class:`IcsBuildError` (loud) rather
    than silently dropping a class from the export.
    """
    blocks: list[tuple[int, str, time, time]] = []
    slots = list(course.class_time or [])
    for day_index, raw in enumerate(slots[:7]):
        slot = raw.strip()
        if slot == "":
            continue
        ordered_codes = [code for code in PERIOD_RANGES if code in slot]
        if len(ordered_codes) != len(set(slot)) or any(
            ch not in PERIOD_RANGES for ch in slot
        ):
            raise IcsBuildError(course_label(course), day_index, raw)
        block = "".join(ordered_codes)
        start = min(PERIOD_RANGES[code][0] for code in ordered_codes)
        end = max(PERIOD_RANGES[code][1] for code in ordered_codes)
        blocks.append((day_index, block, start, end))
    return blocks


def _first_occurrence(semester_start: date, day_index: int) -> date:
    """First calendar date of weekday ``day_index`` (Mon=0) on/after the
    semester start (semester_start itself is a meet-day for that weekday)."""
    delta = (day_index - semester_start.weekday()) % 7
    return semester_start + timedelta(days=delta)


def _vtimezone() -> Timezone:
    """Asia/Taipei: single STANDARD block, +08:00 both ways, no DAYLIGHT.
    Loads Must Not carry historical rules into UNTIL-less events."""
    tzc = Timezone()
    tzc.add("tzid", TAIPEI_TZID)
    std = TimezoneStandard()
    # RFC 5545 §3.6.5: VTIMEZONE DTSTART is a LOCAL naive datetime by spec;
    # attaching tzinfo here would serialize an invalid property.
    std.add("dtstart", datetime(1970, 1, 1, 0, 0, 0))  # noqa: DTZ001
    std.add("tzoffsetfrom", timedelta(hours=8))
    std.add("tzoffsetto", timedelta(hours=8))
    std.add("tzname", "CST")
    tzc.add_component(std)
    return tzc


def build_plan_ics(
    plan_name: str, courses: list[Course], settings: Settings
) -> BuiltIcs:
    """Serialize one plan's catalog-joined courses into an .ics document.

    Item order (the caller's list order) is preserved in event order, so the
    byte output is fully deterministic for identical inputs.
    """
    cal = Calendar()
    cal.add("version", "2.0")
    cal.add("prodid", f"-//{UID_DOMAIN}//NSYSU Course Wrapper//ZH-TW")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", f"NSYSU 課表 - {plan_name.strip() or '未命名'}")
    cal.add_component(_vtimezone())

    # UTC DATE-TIME form of "semester end inclusive" (23:59:59+08:00).
    until_utc = datetime.combine(
        settings.semester_end_date, time(23, 59, 59), tzinfo=_TAIPEI
    ).astimezone(UTC)
    # Stable across regeneration: never "now".
    dtstamp = datetime.combine(
        settings.semester_start_date, time(0, 0), tzinfo=_TAIPEI
    ).astimezone(UTC)

    count = 0
    for course in courses:
        for day_index, block, start_t, end_t in _day_blocks(course):
            first = _first_occurrence(settings.semester_start_date, day_index)
            event = Event()
            event.add("uid", event_uid(course, day_index + 1, block))
            event.add("dtstamp", dtstamp)
            event.add("dtstart", datetime.combine(first, start_t, tzinfo=_TAIPEI))
            event.add("dtend", datetime.combine(first, end_t, tzinfo=_TAIPEI))
            event.add("rrule", vRecur({"freq": "WEEKLY", "until": until_utc}))
            event.add("summary", _summary(course))
            room = (course.room or "").strip()
            if room != "":
                event.add("location", room)
            cal.add_component(event)
            count += 1
    return BuiltIcs(content=cal.to_ical(), event_count=count)
