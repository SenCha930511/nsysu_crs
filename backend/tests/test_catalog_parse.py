"""Parser tests over fixtures (plan todo 6, QA qa/06-parse.log).

Covers: the provisional synthetic page (26-col layout, ZH pagination marker,
HKSCS「喆」 round-trip), the provisional empty page, and - when present -
the live-captured 1151 page with its recorded charset expectation.
"""

from pathlib import Path

import pytest

from app.catalog.parse import (
    _parse_room,
    extract_page_link,
    parse_catalog_page,
    parse_pagination,
)
from app.selcrs.decode import decode_body, resolve_charset

FIXTURES = Path(__file__).parent / "fixtures"
PROVISIONAL = FIXTURES / "dply_page1_provisional.html"
EMPTY = FIXTURES / "dply_empty_provisional.html"
LIVE = FIXTURES / "dply_page_live_1151.html"


def _decoded(path: Path) -> tuple[bytes, str]:
    raw = path.read_bytes()
    return raw, decode_body(raw)


def test_provisional_page_fields():
    # Given: a 3-row synthetic page in the live-verified 26-column layout
    raw, html = _decoded(PROVISIONAL)
    # When: parsed
    page = parse_catalog_page(html, year_sem="1151")
    # Then: charset sniffed to big5hkscs; ZH pagination; every row accepted
    assert resolve_charset(raw) == "big5hkscs"
    assert page.pagination == parse_pagination(html)
    assert (page.pagination.current, page.pagination.total, page.pagination.variant) == (1, 3, "zh")
    assert len(page.rows) == 3
    assert page.skipped_rows == 0

    first, second, third = page.rows
    assert first.year_sem == "1151"
    assert first.dept == "資訊工程學系"
    assert first.grade == "1"
    assert first.class_ == "甲"
    assert first.name_zh == "程式設計(一)"
    assert first.name_en == "Computer Programming (I)"  # badge text must not leak
    assert first.credit == 3
    assert first.compulsory is True
    assert (first.restrict, first.select_n, first.selected_n, first.remaining) == (0, 60, 57, 3)
    assert first.teacher == "陳志明"
    assert first.room == "工EC5022"
    assert first.class_time == ("", "12", "", "", "", "", "")
    assert first.english is False
    assert first.change is None
    assert first.url == "../menu5/showoutline.asp?SYEAR=115&SEM=1&CrsDat=CSE101&Crsname=%B5%7B%A6%A1%B3]%ADp"

    # HKSCS-only char survives big5hkscs round-trip; english marker folded out
    assert second.teacher == "黃喆霖"
    assert "喆" in second.teacher
    assert second.english is True
    assert second.description == "本課程含實地踏查"
    assert second.tags == ("[跨域]",)
    assert second.change == "異動"
    assert second.change_desc == "8/28"
    assert second.compulsory is False

    assert third.change == "新增"
    assert third.remaining == 0
    assert third.class_time == ("34", "", "", "56", "", "", "")


def test_empty_page_is_zero_rows_without_pagination():
    # Given: a page with no candidate rows and no page marker
    _, html = _decoded(EMPTY)
    # When: parsed
    page = parse_catalog_page(html, year_sem="1151")
    # Then: zero rows, zero candidates, no pagination - not an error shape
    assert page.rows == ()
    assert page.candidate_rows == 0
    assert page.pagination is None


def test_pagination_english_variant():
    html = "<p>Showing page 2 of 17 pages</p>"
    pagination = parse_pagination(html)
    assert pagination is not None
    assert (pagination.current, pagination.total, pagination.variant) == (2, 17, "en")


def test_room_extraction_from_fused_time_cell():
    # Given: the live fused time+room cell form (probe 2026-08-28, page 1 row 1)
    # When/Then: room token comes out of the parens; repeated groups dedupe;
    #            plain-room and empty cells fall back sanely
    assert _parse_room("三3,4(社SS 2006)") == "社SS 2006"
    assert _parse_room("一5,6(工EC 5012) 三3,4(工EC 5012)") == "工EC 5012"
    assert _parse_room("工EC5022") == "工EC5022"
    assert _parse_room("") is None


_LIVE_FOOTER = (
    # Verbatim live footer shape (dply_page_live_1151.html): UNQUOTED hrefs.
    '<a href=/menu1/dplycourse.asp?a=2454&D0=1151&DEG_COD=*&page=1>First Page</a>'
    '<a href=/menu1/dplycourse.asp?a=2454&D0=1151&DEG_COD=*&page=2>2</a> '
    '<a href=/menu1/dplycourse.asp?a=2454&D0=1151&DEG_COD=*&page=10>10</a> '
    '<a href=/menu1/dplycourse.asp?a=2454&D0=1151&DEG_COD=*&page=2>Next Page</a>'
    '<a href=/menu1/dplycourse.asp?a=2454&D0=1151&DEG_COD=*&page=141>Last Page</a>'
)


def test_extract_page_link_exact_and_unquoted():
    # Given: the live unquoted-href footer (regression: anchored char class)
    # When/Then: exact target wins; substring traps (page=2 vs page=141) do not fire
    assert extract_page_link(_LIVE_FOOTER, 2) == "/menu1/dplycourse.asp?a=2454&D0=1151&DEG_COD=*&page=2"
    assert extract_page_link(_LIVE_FOOTER, 141).endswith("page=141")


def test_extract_page_link_synthesizes_out_of_window_targets():
    # Given a target not in the numbered window (e.g. 25 while 1..10 shown)
    # When/Then: any sibling link is reused with its page param substituted
    link = extract_page_link(_LIVE_FOOTER, 25)
    assert link is not None and link.endswith("page=25") and "a=2454" in link


def test_extract_page_link_none_on_single_page():
    assert extract_page_link("<table><tr><td>no paging here</td></tr></table>", 2) is None


@pytest.mark.skipif(not LIVE.exists(), reason="live fixture not captured yet")
def test_live_fixture_rows_and_charset():
    # Given: the live-captured 1151 page 1 of 141 (raw wire bytes, 20 rows)
    raw, html = _decoded(LIVE)
    # When: parsed
    page = parse_catalog_page(html, year_sem="1151")
    # Then: the EN form wins (the live footer carries both marker forms)
    assert page.pagination is not None
    assert (page.pagination.current, page.pagination.total, page.pagination.variant) == (1, 141, "en")
    assert len(page.rows) == 20
    assert page.skipped_rows == 0
    for row in page.rows:
        assert row.year_sem == "1151"
        assert len(row.class_time) == 7
        assert row.credit is not None
        for quota in (row.restrict, row.select_n, row.selected_n, row.remaining):
            assert quota is not None
        # Live name cells nest everything inside <small>; extraction must
        # still yield both names (regression: badge-removal nulled both).
        assert row.name_zh
        assert row.name_en
        # Live room cells are fused TIME+ROOM ("三3,4(社SS 2006)"); the
        # stored room is the extracted parens token, never the fused string.
        assert row.room is None or "(" not in row.room
    # And: the paging link for page 2 is extractable from the live footer
    link = extract_page_link(html, 2)
    assert link is not None and link.endswith("page=2") and "a=" in link
    # And: the detected charset matches the conclusion recorded in the facts doc
    assert resolve_charset(raw) in ("big5hkscs", "utf-8")
