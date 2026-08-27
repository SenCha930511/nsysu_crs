"""Course catalog query domain logic (plan todo 7).

Pure, side-effect-free parsing and SQL construction for ``GET /api/courses``;
the only coroutine here (``fetch_page``) executes the two SELECTs. Every
validation failure raises ``CourseQueryError`` with a user-facing message so
the API layer can map it 1:1 onto a 400 response.

Filter contract (plan todo 7 / References):
- ``period`` = the timeslot code must be CONTAINED in the class_time string of
  the given ``weekday`` (class_time slots are Monday..Sunday, 0..6).
- Legal timeslot codes mirror NSYSUSelectorHelper TIMESLOT: A,1..4,B,5..9,C,D,E,F.
- Legal grades mirror the scraped catalog's 年級 domain (0 = 不分年級, 1..4),
  verified against the live 1151 snapshot; grade=9 must 400 (todo 7 QA).
"""

from dataclasses import dataclass
from typing import Final

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.models.courses import Course

#: Fixed page size (plan todo 7: 每頁 50).
PER_PAGE: Final = 50

#: Legal single timeslot codes (A,1..4,B,5..9,C,D,E,F).
PERIODS: Final = frozenset("A123456789BCDEF")

#: Legal grade values in the scraped catalog (0 = 不分年級).
GRADES: Final = frozenset("01234")

#: Recognized query parameter names on GET /api/courses.
QUERY_PARAMS: Final = frozenset(
    {"year_sem", "q", "dept", "grade", "credit", "compulsory",
     "english", "weekday", "period", "page"}
)

_BOOL_VALUES: Final = {"true": True, "false": False, "1": True, "0": False}


class CourseQueryError(ValueError):
    """An illegal /api/courses query parameter (mapped to HTTP 400)."""


@dataclass(frozen=True, slots=True)
class CourseFilter:
    """One validated /api/courses query (parsed boundary value)."""

    year_sem: str
    q: str | None
    dept: str | None
    grade: str | None
    credit: int | None
    compulsory: bool | None
    english: bool | None
    weekday: int | None  # 1 (Mon) .. 7 (Sun)
    period: str | None  # single timeslot code, only meaningful with weekday
    page: int  # 1-based


def parse_course_params(
    raw: object, *, default_year_sem: str
) -> CourseFilter:
    """Parse raw query params into a validated CourseFilter.

    ``raw`` is any Mapping[str, str] (Starlette QueryParams in production,
    plain dicts in tests). Raises CourseQueryError with a clear message for
    unknown names, out-of-domain values, or the period-without-weekday combo.
    """
    keys = list(raw.keys())  # type: ignore[attr-defined]

    def value(name: str) -> str | None:
        # Mapping.get on the MultiDict returns the last occurrence.
        return raw.get(name)  # type: ignore[attr-defined]

    def first_key_not_allowed() -> str | None:
        for key in keys:
            if key not in QUERY_PARAMS:
                return key
        return None

    def field(name: str) -> str | None:
        got = value(name)
        if got is None or got.strip() == "":
            return None
        return got.strip()

    def parse_bool(name: str) -> bool | None:
        got = field(name)
        if got is None:
            return None
        parsed = _BOOL_VALUES.get(got.lower())
        if parsed is None:
            raise CourseQueryError(
                f"{name} must be a boolean (true/false/1/0), got {got!r}"
            )
        return parsed

    def parse_int(name: str) -> int | None:
        got = field(name)
        if got is None:
            return None
        if not got.isdigit():
            raise CourseQueryError(
                f"{name} must be a non-negative integer, got {got!r}"
            )
        return int(got)

    bad_key = first_key_not_allowed()
    if bad_key is not None:
        allowed = ", ".join(sorted(QUERY_PARAMS))
        raise CourseQueryError(
            f"unknown query parameter {bad_key!r}; supported: {allowed}"
        )

    page_raw = field("page")
    if page_raw is not None and (not page_raw.isdigit() or int(page_raw) < 1):
        raise CourseQueryError(f"page must be an integer >= 1, got {page_raw!r}")
    page = int(page_raw) if page_raw is not None else 1

    year_sem = field("year_sem") or default_year_sem
    if not (year_sem.isdigit() and len(year_sem) == 4):
        raise CourseQueryError(
            f"year_sem must be a 4-digit semester like '1151', got {year_sem!r}"
        )

    grade = field("grade")
    if grade is not None and grade not in GRADES:
        raise CourseQueryError(
            f"grade must be one of {', '.join(sorted(GRADES))} (0 = 不分年級), "
            f"got {grade!r}"
        )

    weekday = parse_int("weekday")
    if weekday is not None and not 1 <= weekday <= 7:
        raise CourseQueryError(f"weekday must be 1 (Mon) .. 7 (Sun), got {weekday}")

    period_raw = field("period")
    period: str | None = None
    if period_raw is not None:
        period = period_raw.upper()
        if len(period) != 1 or period not in PERIODS:
            raise CourseQueryError(
                f"period must be a single timeslot code ({''.join(sorted(PERIODS))}), "
                f"got {period_raw!r}"
            )
        if weekday is None:
            raise CourseQueryError("period requires weekday (the day to match on)")

    return CourseFilter(
        year_sem=year_sem,
        q=field("q"),
        dept=field("dept"),
        grade=grade,
        credit=parse_int("credit"),
        compulsory=parse_bool("compulsory"),
        english=parse_bool("english"),
        weekday=weekday,
        period=period,
        page=page,
    )


def resolve_year_sem(catalog_max: str | None, settings_default: str) -> str:
    """Default year_sem: the freshest semester in the catalog, else settings."""
    return catalog_max if catalog_max is not None else settings_default


def _filters(f: CourseFilter) -> list[ColumnElement[bool]]:
    clauses: list[ColumnElement[bool]] = [Course.year_sem == f.year_sem]
    if f.q is not None:
        like = f"%{f.q}%"
        clauses.append(
            or_(
                Course.name_zh.ilike(like),
                Course.name_en.ilike(like),
                Course.teacher.ilike(like),
            )
        )
    if f.dept is not None:
        clauses.append(Course.dept == f.dept)
    if f.grade is not None:
        clauses.append(Course.grade == f.grade)
    if f.credit is not None:
        clauses.append(Course.credit == f.credit)
    if f.compulsory is not None:
        clauses.append(Course.compulsory.is_(f.compulsory))
    if f.english is not None:
        clauses.append(Course.english.is_(f.english))
    if f.weekday is not None:
        # class_time slots are Monday..Sunday at indexes 0..6 (JSONB ->> text).
        slot = Course.class_time[f.weekday - 1].astext
        clauses.append(slot.isnot(None))
        if f.period is not None:
            # Period codes are letters/digits only: no LIKE metachar escaping.
            clauses.append(slot.ilike(f"%{f.period}%"))
        else:
            clauses.append(slot != "")
    return clauses


def build_items_query(f: CourseFilter) -> Select[tuple[Course]]:
    """Page slice SELECT: stable order (dept, name, id) so pages never drift."""
    return (
        select(Course)
        .where(*_filters(f))
        .order_by(Course.dept.nulls_last(), Course.name_zh.nulls_last(), Course.id)
        .limit(PER_PAGE)
        .offset((f.page - 1) * PER_PAGE)
    )


def build_count_query(f: CourseFilter) -> Select[tuple[int]]:
    """Total-row SELECT for the same filter set (drives paging math)."""
    return select(func.count()).select_from(Course).where(*_filters(f))


async def fetch_page(
    session: AsyncSession, f: CourseFilter
) -> tuple[list[Course], int]:
    """Run the count + slice SELECTs; returns (items, total)."""
    total = (await session.execute(build_count_query(f))).scalar_one()
    rows = (await session.execute(build_items_query(f))).scalars().all()
    return list(rows), total
