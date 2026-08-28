"""dplycourse catalog page parser (plan todo 6).

The positional column layout below is a REWRITE informed by the MIT-licensed
reference implementation:

    NSYSUCourseAPI - https://github.com/NSYSU-OpenDev/NSYSUCourseAPI
    MIT License, Copyright (c) 2024 NSYSU Open Development Community
    Reference file: utils/parse_info.py
    https://raw.githubusercontent.com/NSYSU-OpenDev/NSYSUCourseAPI/main/utils/parse_info.py

Layout contract (live page-1 probe 2026-08-28 + the 141-page captured run
qa/06-live.log; see docs/verified-facts.md): each course <tr> has 25 direct
<td> children (the old reference asserted >= 26 including a trailing pad;
MIN_CELLS stays at the observed-live 25 so banner rows stay excluded) -

    [0]  change marker        ("" | 異動 | 新增)
    [1]  change description   (e.g. "7/15")
    [2]  multiple-compulsory  ("*" | " ") - parsed, not stored (no DB column)
    [3]  department
    [4]  short course id      (e.g. STP101 - NOT the 8-char code)
    [5]  grade
    [6]  class section
    [7]  course name          LIVE: <small><a href=showoutline>中文</a><br>
                            <font>ENGLISH</font></small>; provisional:
                            中文 <br> 英文 <small>(<a>課程大綱</a>)</small>
                            (both shapes handled in _parse_name_and_url)
    [8]  credit
    [9]  term marker          (年 | 期) - parsed, not stored
    [10] compulsory marker    (必 | 選)
    [11] restrict
    [12] select (點選)
    [13] selected (選上)
    [14] remaining
    [15] teacher
    [16] fused time+room cell, e.g. "三3,4(社SS 2006)"; the room token(s)
         live inside (...) parens LIVE (plain-room cells stay verbatim;
         reference stores this cell raw - we extract, see _parse_room)
    [17:24] weekly time slots, Monday..Sunday (e.g. "56", "")
    [24]  description cell; <font> children are tag badges

Rows failing the acceptance checks in ``_accept`` are SKIPPED and counted
(mirroring the reference's False-on-error policy: one malformed row must not
kill a multi-thousand-row ingest); the ingest layer treats "every candidate
row failed" as a layout-break error. Header rows use <th> (excluded by the
<td> rule); banner rows have one colspan cell (excluded by MIN_CELLS).
"""

import re
from dataclasses import dataclass
from typing import Final

from bs4 import BeautifulSoup, Tag

from app.catalog.rows import WEEKDAY_SLOTS, CatalogRow

#: Minimum direct <td> children for a row to be a course-row candidate.
MIN_CELLS: Final = 25

#: Position of the school's 8-char 課程代碼 column IF the page has one.
#: Live finding (full 141-page run 2026-08-28, qa/06-live.log +
#: docs/verified-facts.md "dplycourse rows and the 8-char course code"):
#: dplycourse has NO 課程代碼 column. [4] is the variable-length short
#: 課號 (STP101..8-char GEAE2526-family, 486 rows); [17:24] can hold 8-period
#: full-day strings ("12345678"); the slt_result-observed M3046243-family
#: NEVER appears -> None, courses.code stays NULL and the fallback identity
#: in rows.py applies (documented 缺碼行為).
CODE_CELL_INDEX: Final[int | None] = None

_CODE_8_RE: Final = re.compile(r"^[A-Za-z0-9]{8}$")
_INT_RE: Final = re.compile(r"^-?\d+$")
_ROOM_PARENS_RE: Final = re.compile(r"\(([^()]*)\)")

#: 課別代號 (CSE515/STP101...) inside every catalog row's showoutline link:
#: live-verified (dply_page_live_1151.html + the 2026-08-28 write-probe that
#: CSE515 resolves at chk_crsno_desc.asp while the 8-char 課程代碼 does not).
_CRSDAT_RE: Final = re.compile(r"[?&]CrsDat=([^&]*)")

_CHANGE_MARKERS: Final = frozenset({"", "異動", "新增"})
_TERM_MARKERS: Final = frozenset({"年", "期"})
_COMP_MARKERS: Final = frozenset({"必", "選"})

_PAGINATION_EN_RE: Final = re.compile(
    r"Showing\s+page\s+(\d+)\s+of\s+(\d+)\s+pages?", re.IGNORECASE
)
_PAGINATION_ZH_RE: Final = re.compile(r"第\s*(\d+)\s*[/／]\s*(\d+)\s*頁")

# Paging footer anchors: /menu1/dplycourse.asp?a=<token>&...&page=N (live
# paging contract 2026-08-28 - pages 2..N are GETs on these links, see
# docs/verified-facts.md).
_PAGE_LINK_RE: Final = re.compile(r"href=[\"']?(/menu1/dplycourse\.asp\?[^\"'<>\s]*)")


@dataclass(frozen=True, slots=True)
class Pagination:
    """'Showing page X of N' / 「第 X / Y 頁」 marker; ``variant`` records
    which text form produced it (en | zh) for the facts log."""

    current: int
    total: int
    variant: str


@dataclass(frozen=True, slots=True)
class ParsedCatalogPage:
    """Parse outcome for one page: rows that passed acceptance, rows that
    looked like candidates but failed (skipped), and candidate count."""

    pagination: Pagination | None
    rows: tuple[CatalogRow, ...]
    skipped_rows: int
    candidate_rows: int


def parse_pagination(html: str) -> Pagination | None:
    """Extract the page X-of-N marker; EN form wins when both are present."""
    en = _PAGINATION_EN_RE.search(html)
    if en is not None:
        return Pagination(current=int(en.group(1)), total=int(en.group(2)), variant="en")
    zh = _PAGINATION_ZH_RE.search(html)
    if zh is not None:
        return Pagination(current=int(zh.group(1)), total=int(zh.group(2)), variant="zh")
    return None


def _page_param(path: str) -> int | None:
    match = re.search(r"[?&]page=(\d+)(?:&|$)", path)
    return int(match.group(1)) if match is not None else None


def extract_page_link(html: str, target_page: int) -> str | None:
    """Root-relative paging-link href for ``target_page``, verbatim.

    The footer's numbered window covers ±10 pages and always includes a
    Next-page anchor; far targets synthesize from any sibling link by
    substituting the ``page`` param (the ``a`` token + filter echo belong to
    the same result set, so the substitution preserves the session's query).
    Returns None when the page carries no paging link at all (single page).
    """
    paths = _PAGE_LINK_RE.findall(html)
    numbered = [(path, _page_param(path)) for path in paths]
    for path, number in numbered:
        if number == target_page:
            return path
    for path, number in numbered:
        if number is not None:
            return re.sub(r"([?&]page=)\d+", rf"\g<1>{target_page}", path)
    return None


def _cell_text(cell: Tag) -> str:
    """Visible cell text with <br> folded to newlines (name = zh\\nen)."""
    for line_break in cell.find_all("br"):
        line_break.replace_with("\n")
    # NBSP shows up in Big5-era cells; normalize to a plain space, then trim.
    return cell.get_text().replace(" ", " ").strip()


def _is_int(text: str) -> bool:
    return bool(_INT_RE.match(text))


def _accept(texts: list[str]) -> bool:
    """Course-row acceptance checks (rewrite of the reference's asserts)."""
    if len(texts) < MIN_CELLS:
        return False
    if texts[0] not in _CHANGE_MARKERS:
        return False
    if not texts[5]:  # grade
        return False
    if not _is_int(texts[8]):  # credit
        return False
    if texts[9] not in _TERM_MARKERS:
        return False
    if texts[10] not in _COMP_MARKERS:
        return False
    return all(_is_int(texts[index]) for index in (11, 12, 13, 14))


def _parse_description(cell: Tag) -> tuple[str, tuple[str, ...], bool]:
    """Split the description cell into (text, tag-badges, english-taught)."""
    tags: list[str] = []
    for badge in cell.find_all("font"):
        tag_text = " ".join(badge.get_text().split())
        if tag_text:
            tags.append(tag_text)
        badge.extract()
    description = _cell_text(cell)
    english = "※英語授課" in description
    # The english marker may appear mid-text; remove every occurrence.
    description = " ".join(description.replace("※英語授課", "").split())
    return description, tuple(tags), english


def _parse_name_and_url(cell: Tag) -> tuple[str | None, str | None, str | None]:
    """Extract (name_zh, name_en, outline_url) from the name cell.

    Two shapes exist. LIVE (verified 2026-08-28, dply_page_live_1151.html):
    everything sits inside ONE ``<small>`` - ``<a href=showoutline...>中文
    </a><br><font>ENGLISH</font>``; here the anchor text IS the Chinese name
    and the <font> the English one. PROVISIONAL fixture shape: the names sit
    outside and a ``<small>(<a>課程大綱</a>)</small>`` badge follows them;
    badges are removed before the 「中文\n英文」 split. The structural
    discriminator is whether the outline anchor's own <small> also carries
    the English <font>.
    """
    link = cell.select_one('a[href*="showoutline"]')
    url = str(link["href"]) if link is not None else None
    if link is not None:
        owner = link.find_parent("small")
        if owner is not None:
            font = owner.find("font")
            if font is not None:
                zh = link.get_text(strip=True)
                en = font.get_text(strip=True)
                return zh or None, en or None, url
    for badge in cell.find_all("small"):
        badge.extract()
    zh, _, en = _cell_text(cell).partition("\n")
    return zh.strip() or None, en.strip() or None, url


def _parse_room(text: str) -> str | None:
    """Extract room from the fused time+room cell (live: "三3,4(社SS 2006)").

    Parens hold the room; a multi-slot row can repeat the pattern
    ("一5,6(工EC 5012) 三3,4(工EC 5012)"), so groups are deduplicated in
    order. Cells without parens (provisional fixture's plain "工EC5022",
    rooms like "未定") stay verbatim; empty -> None.
    """
    if not text:
        return None
    rooms = list(dict.fromkeys(group.strip() for group in _ROOM_PARENS_RE.findall(text) if group.strip()))
    return ", ".join(rooms) if rooms else text


def _parse_code(texts: list[str]) -> str | None:
    """8-char school course code, only from the discovered column position."""
    if CODE_CELL_INDEX is None or len(texts) <= CODE_CELL_INDEX:
        return None
    candidate = texts[CODE_CELL_INDEX]
    return candidate if _CODE_8_RE.match(candidate) else None


def _derive_code_from_url(url: str | None) -> str | None:
    """課別代號 from the row's own showoutline link (the write-form identifier)."""
    if url is None:
        return None
    match = _CRSDAT_RE.search(url)
    return match.group(1) if match is not None else None


def _parse_row(cells: list[Tag], texts: list[str], *, year_sem: str) -> CatalogRow:
    description, tags, english = _parse_description(cells[24])
    name_zh, name_en, url = _parse_name_and_url(cells[7])
    class_time = tuple(texts[17 : 17 + WEEKDAY_SLOTS])
    return CatalogRow(
        year_sem=year_sem,
        code=_parse_code(texts) or _derive_code_from_url(url),
        dept=texts[3] or None,
        grade=texts[5] or None,
        class_=texts[6] or None,
        name_zh=name_zh,
        name_en=name_en,
        credit=int(texts[8]),
        compulsory=texts[10] == "必",
        restrict=int(texts[11]),
        select_n=int(texts[12]),
        selected_n=int(texts[13]),
        remaining=int(texts[14]),
        teacher=texts[15] or None,
        room=_parse_room(texts[16]),
        class_time=class_time,
        description=description or None,
        tags=tags,
        english=english,
        change=texts[0] or None,
        change_desc=texts[1] or None,
        url=url,
    )


def parse_catalog_page(html: str, *, year_sem: str) -> ParsedCatalogPage:
    """Parse one decoded dplycourse page into pagination + normalized rows."""
    soup = BeautifulSoup(html, "html.parser")
    rows: list[CatalogRow] = []
    skipped = 0
    candidates = 0
    for tr in soup.find_all("tr"):
        cells = tr.find_all("td", recursive=False)
        if len(cells) < MIN_CELLS:
            continue
        candidates += 1
        texts = [_cell_text(cell) for cell in cells]
        if not _accept(texts):
            skipped += 1
            continue
        rows.append(_parse_row(cells, texts, year_sem=year_sem))
    return ParsedCatalogPage(
        pagination=parse_pagination(html),
        rows=tuple(rows),
        skipped_rows=skipped,
        candidate_rows=candidates,
    )
