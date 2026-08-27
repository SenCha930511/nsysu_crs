"""Shared value objects for the self-hosted catalog pipeline (plan todo 6).

``CatalogRow`` is the parsed boundary value for one dplycourse <tr> - a pure
data object with no school/DB concerns. Persistence maps it onto the
``courses`` table; the fallback identity below is the documented stable key
for rows whose 8-char school course code is NULL (see docs/verified-facts.md,
"dplycourse rows and the 8-char course code").
"""

from dataclasses import dataclass
from typing import Final

#: class_time has one slot per weekday, Monday .. Sunday (7 slots).
WEEKDAY_SLOTS: Final = 7


@dataclass(frozen=True, slots=True)
class CatalogRow:
    """One normalized catalog row for a semester (DB column parity).

    ``code`` is the school's 8-char course code when the page exposes one,
    else None - the ``unique(year_sem, code)`` constraint treats NULLs as
    distinct, so NULL-code rows use ``fallback_key`` for identity instead.
    """

    year_sem: str
    code: str | None
    dept: str | None
    grade: str | None
    class_: str | None
    name_zh: str | None
    name_en: str | None
    credit: int | None
    compulsory: bool
    restrict: int | None
    select_n: int | None
    selected_n: int | None
    remaining: int | None
    teacher: str | None
    room: str | None
    class_time: tuple[str, ...]
    description: str | None
    tags: tuple[str, ...]
    english: bool
    change: str | None
    change_desc: str | None
    url: str | None

    def fallback_key(self) -> tuple[object, ...]:
        """Stable identity for NULL-code rows (documented choice):

        (year_sem, dept, name_zh, teacher, room, class_time) - the plan's
        degraded identity for missing course codes: the same course name
        taught by the same teacher in the same room at the same slot set is
        the same section in practice (todo 12 reuses this identity for ICS
        UIDs when ``code`` is absent).
        """
        return (
            self.year_sem,
            self.dept,
            self.name_zh,
            self.teacher,
            self.room,
            self.class_time,
        )
