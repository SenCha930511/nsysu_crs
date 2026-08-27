"""slt_result.asp parser (plan todo 9).

Parses the school's 「選課表」 page into normalized selection items. The REAL
layout (docs/verified-facts.md item (c), fixture
``backend/tests/fixtures/slt_result_live_1151.html``) is **14 columns**::

    [0]選上與否 [1]系所別 [2]課號 [3]年級 [4]課程代碼 [5]課程名稱 [6]點數志願
    [7]階段 [8]學分 [9]學年期 [10]必選修 [11]授課教師 [12]教室 [13]說明

Two verified row-shape variants are handled by cell count alone (banner /
summary / section-title rows all render as a single ``colspan`` cell and are
skipped):

- **14 cells** — a選上-section row (banner ``※ ※ 選上課程 ※ ※``); carries the
  8-char 課程代碼 in ``[4]``.
- **13 cells** — a 「選課期間錯誤訊息」 error-section row (fixture
  ``bgcolor=#CCFFCC`` table); **no 課程代碼 column**, so indices shift by one
  from 課程名稱 onward and ``code`` is None. Cell ``[0]`` is 「失敗」.
- **7 cells** — the superseded *provisional* layout
  (``狀態/課程名稱/學分/必選修/教師/上課時間/備註``, provisional fixture only;
  kept as a marked test variant). No 課號/課程代碼 columns at all.

State (cell ``[0]``) is normalized to 選上 | 登記加選 | 失敗； the provisional
failure marker 「加選失敗」 folds into 失敗. Unrecognized non-empty markers are
kept verbatim (a new school marker must not kill a whole sync).

Column fusion: ``[12]教室`` fuses weekday+periods and room
(e.g. ``三2,3,4(工EC 5012)``). Split into ``times``/``room`` ONLY when the
whole cell matches the fused shape exactly; anything else keeps the raw text
in ``room_text`` with ``times``/``room`` None (todo 10 builds its grid from
the catalog class_time, not from here).

Expiry detection (dead school session): the school serves its login page or a
「請先登錄」 bounce with HTTP 200 instead of the 選課表. Both markers are
checked BEFORE row parsing; a page with neither marker nor the 學生課表 anchor
is unrecognized school behaviour -> SelcrsUnavailable (never silently parsed
into an empty selection list).
"""

import re
from typing import Final

from bs4 import BeautifulSoup, Tag
from pydantic import BaseModel, ConfigDict

from app.selcrs.errors import SelcrsSessionExpired, SelcrsUnavailable

#: Page anchors: the live page is titled 學生課表; the provisional variant is
#: 選課結果查詢; the real header row fuses 選上與否. Any one present = this is
#: a selections page; login pages carry none of them.
_PAGE_ANCHORS: Final = ("學生課表", "選課結果", "選上與否")

#: Dead-session markers: the 請先登錄 bounce text or the SSO2 login form itself.
_EXPIRED_MARKERS: Final = ("請先登錄", "請先登入", "SPassword", "Studcheck_sso2")

#: Header row first-cell texts (real header fuses 選上<BR>與否; provisional is 狀態).
_HEADER_FIRST_CELLS: Final = ("選上與否", "狀態")

_STATE_NORMALIZE: Final = {
    "選上": "選上",
    "登記加選": "登記加選",
    "失敗": "失敗",
    "加選失敗": "失敗",  # provisional failure wording
}

#: Whole-cell fused 教室 shape: 三2,3,4(工EC 5012) / 五6(工EC 2011).
_FUSED_ROOM: Final = re.compile(r"^([一二三四五六日][0-9A-Ea-e,，]+)\(([^()]*)\)$")


class SelectionItem(BaseModel):
    """One normalized slt_result row (the deliverable shape of todo 9).

    ``code`` (8-char 課程代碼) is None on error-section rows (that table has
    no code column) and on provisional rows. ``course_no`` is the short 課號
    (e.g. CSE515). ``unknown``/``course_id`` are filled by the catalog join
    (``join.py``), never by this parser.
    """

    model_config = ConfigDict(frozen=True)

    code: str | None
    course_no: str | None
    state: str
    dept: str
    name: str
    credit: int | None
    compulsory_elective: str
    teacher: str
    room_text: str
    points_priority: int | None
    stage: str
    year_semest_note: str
    # Fused 教室 split (None when the cell does not match the fused shape).
    times: str | None
    room: str | None
    # Catalog join results (unknown=True when the code is absent/unmatched).
    unknown: bool
    course_id: str | None


def _clean(cell: Tag) -> str:
    """Cell text with tags flattened and &nbsp; treated as padding."""
    return cell.get_text(separator="").replace("\xa0", " ").strip()


def _to_int(text: str) -> int | None:
    """Digit cells (學分/點數志願) -> int; empty/non-digit -> None."""
    return int(text) if text.isdigit() else None


def _split_room(fused: str) -> tuple[str | None, str | None]:
    """Best-effort 教室 split: (times, room) or (None, None) when unfused."""
    match = _FUSED_ROOM.match(fused)
    if match is None:
        return None, None
    room = match.group(2).strip()
    return match.group(1), room if room else None


def _base_item(cells: list[Tag]) -> SelectionItem | None:
    """Normalize one data row by cell count; None for header/junk rows."""
    texts = [_clean(cell) for cell in cells]
    if not texts[0]:
        return None
    if texts[0] in _HEADER_FIRST_CELLS:
        return None
    state = _STATE_NORMALIZE.get(texts[0], texts[0])
    if len(texts) == 14:  # real 選上 section (has 課程代碼)
        code = texts[4] or None
        course_no = texts[2] or None
        name, points, stage, credit = texts[5], texts[6], texts[7], texts[8]
        note, comp, teacher, room_text = texts[9], texts[10], texts[11], texts[12]
        dept = texts[1]
    elif len(texts) == 13:  # real 錯誤訊息 section (no 課程代碼 column)
        code = None
        course_no = texts[2] or None
        name, points, stage, credit = texts[4], texts[5], texts[6], texts[7]
        note, comp, teacher, room_text = texts[8], texts[9], texts[10], texts[11]
        dept = texts[1]
    elif len(texts) == 7:  # provisional layout (marked variant)
        code = None
        course_no = None
        name, points, stage, credit = texts[1], "", "", texts[2]
        note, comp, teacher, room_text = "", texts[3], texts[4], texts[5]
        dept = ""
    else:  # unknown row shape: skip rather than guess columns
        return None
    times, room = _split_room(room_text)
    return SelectionItem(
        code=code,
        course_no=course_no,
        state=state,
        dept=dept,
        name=name,
        credit=_to_int(credit),
        compulsory_elective=comp,
        teacher=teacher,
        room_text=room_text,
        points_priority=_to_int(points),
        stage=stage,
        year_semest_note=note,
        times=times,
        room=room,
        unknown=True,  # join.py may flip this; parser never matches
        course_id=None,
    )


def parse_slt_result(html: str) -> list[SelectionItem]:
    """Parse one decoded slt_result page into normalized selection items.

    Raises:
        SelcrsSessionExpired: the page is the school login page / 請先登錄
            bounce (dead jar) -> API maps to 401 SELCRS_EXPIRED.
        SelcrsUnavailable: neither the schedule anchor nor an expiry marker
            is present (unrecognized school behaviour -> breaker path).
    """
    if any(marker in html for marker in _EXPIRED_MARKERS):
        raise SelcrsSessionExpired("slt_result bounced to the school login page")
    if not any(anchor in html for anchor in _PAGE_ANCHORS):
        raise SelcrsUnavailable("slt_result returned an unrecognized page shape")
    soup = BeautifulSoup(html, "html.parser")
    items: list[SelectionItem] = []
    for row in soup.find_all("tr"):
        # Banner/summary/section rows render as ONE colspan cell -> skipped by count.
        cells = row.find_all(["td", "th"], recursive=False)
        if len(cells) not in (7, 13, 14):
            continue
        item = _base_item(cells)
        if item is not None:
            items.append(item)
    return items
