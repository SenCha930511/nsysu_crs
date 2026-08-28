"""slt_result parser fixture tests (plan todo 9; QA qa/09-parse.log).

The REAL 14-column live fixture (student id masked; re-captured 2026-08-28
morning, docs/verified-facts.md capture-run sections) is ground truth:
5 選上 rows and NO error section (the school resolved the 2026-08-27
 duplicate-add rows into plain selections). The 失敗 error-section shape
(13 cells, no 課程代碼 column) is pinned by a synthetic page modeled
cell-for-cell on the real 2026-08-27 section rows. 登記加選 does not occur
in the live fixture (page captured outside 初選); it stays pinned by a
synthetic real-layout row. The superseded provisional 7-column layout stays
as a marked variant.
"""

from collections import Counter
from pathlib import Path

import pytest

from app.selections.parse import parse_slt_result
from app.selcrs.decode import decode_body
from app.selcrs.errors import SelcrsSessionExpired, SelcrsUnavailable

FIXTURES = Path(__file__).parent / "fixtures"


def _live_html() -> str:
    # The live fixture declares charset=utf-8 and is valid UTF-8 bytes
    # (verified-facts decoding-policy correction); decode via the real layer.
    raw = (FIXTURES / "slt_result_live_1151.html").read_bytes()
    return decode_body(raw, None)


# ---------- real live fixture ----------


def test_real_fixture_parses_all_rows_with_state_counts():
    # Given the real 115-1 slt_result page (no error section since the
    # 2026-08-28 morning re-capture)
    # When parsed
    items = parse_slt_result(_live_html())
    # Then every data row survives: 5 選上 rows, nothing else
    assert len(items) == 5
    assert Counter(item.state for item in items) == {"選上": 5}


def test_real_fixture_spot_check_known_selected_row():
    items = parse_slt_result(_live_html())
    first = items[0]
    # The documented first row (col-by-col per verified-facts item (c))
    assert first.code == "M3046243"
    assert first.course_no == "CSE515"
    assert first.state == "選上"
    assert first.dept == "資工碩"
    assert first.name == "高等電腦網路"
    assert first.credit == 3
    assert first.compulsory_elective == "必"
    assert first.teacher == "林俊宏"
    assert first.room_text == "三2,3,4(工EC 5012)"
    assert first.times == "三2,3,4"
    assert first.room == "工EC 5012"
    assert first.points_priority == 0
    assert first.stage == "0"
    assert first.year_semest_note == "期"
    assert first.unknown is True and first.course_id is None


def test_real_fixture_row_with_points_priority_value():
    # Given the live fixture, the selected 專題研究（一）/資料處理與建模 rows
    # carry non-zero 點數志願 and stage 22 (course_no also appears in the
    # 失敗 section, so key on the selected rows only)
    selected = {i.course_no: i for i in parse_slt_result(_live_html()) if i.state == "選上"}
    assert selected["CSE530"].points_priority == 2
    assert selected["CSE530"].code == "M30400B1"
    assert selected["CSE729"].points_priority == 1
    assert selected["CSE729"].stage == "22"


def _synthetic_failed_section_page() -> str:
    """One 選上 row plus the error table, mirroring the REAL 13-cell
    「選課期間錯誤訊息」 rows of the 2026-08-27 capture cell-for-cell (the
    live fixture no longer carries an error section since the 2026-08-28
    morning re-capture, so the shape is pinned here)."""
    return """<html><head><title>學生課表 Course Schedule</title></head><body>
<table border=1><tr><td>選上與否</td></tr>
<TR><td colspan=14>※ ※  選上課程  ※ ※</td></TR>
<tr><td><p><small>選上</small></p></td><td><small>資工碩</small></td>
<td><small>CSE515</small></td><td><small>1</small></td><td><small>M3046243</small></td>
<td><small><a href=x>高等電腦網路</a></small></td><td><small>0</small></td>
<td><small>0</small></td><td><small>3</small></td><td><small>期</small></td>
<td><small>必</small></td><td><small>林俊宏</small></td>
<td><small>三2,3,4(工EC 5012) </small></td><td><small>&nbsp;</small></td></TR>
</table>
<table cellspacing=0 cellpadding=2 border=1 width="100%" bgcolor=#CCFFCC>
<TR><td align="center" colspan=13><small>選課期間錯誤訊息</small></td></TR>
<TR><td align="center" width=30><p align="center"><small>失敗</small></p></td>
<td align="middle" width=50><small>資工碩</small></td>
<td align="middle" width=50><small>CSE530</small></td>
<td align="middle" width=10><small>0</small></td>
<td align="middle" width=90><small><a href=x>專題研究（一）</a></small></td>
<td align="middle" width=10><small>&nbsp;</small></td>
<td align="middle" width=20><small>22</small></td>
<td align="middle" width=20><small>3</small></td>
<td align="middle" width=20><small>期</small></td>
<td align="middle" width=20><small>選</small></td>
<td align="middle" width=40><small>邱勝敏</small></td>
<td align="middle" width=40><small>一2,3,4(工EC 5000) </small></td>
<td align="middle" width=80><small>所選課號 CSE530 重複加選！<br>Course CSE530 has been selected twice !</small></td></TR>
<TR><td align="center" width=30><p align="center"><small>失敗</small></p></td>
<td align="middle" width=50><small>資工碩</small></td>
<td align="middle" width=50><small>CSE729</small></td>
<td align="middle" width=10><small>0</small></td>
<td align="middle" width=90><small><a href=x>資料處理與建模</a></small></td>
<td align="middle" width=10><small>&nbsp;</small></td>
<td align="middle" width=20><small>22</small></td>
<td align="middle" width=20><small>3</small></td>
<td align="middle" width=20><small>期</small></td>
<td align="middle" width=20><small>選</small></td>
<td align="middle" width=40><small>邱勝敏</small></td>
<td align="middle" width=40><small>四2,3,4(工EC 1006) </small></td>
<td align="middle" width=80><small>所選課號 CSE729 重複加選！<br>Course CSE729 has been selected twice !</small></td></TR>
</table></body></html>"""


def test_failed_section_rows_parse_from_real_layout():
    # Given the real-layout error section (13 cells, no 課程代碼 column)
    items = parse_slt_result(_synthetic_failed_section_page())
    assert Counter(item.state for item in items) == {"選上": 1, "失敗": 2}
    # Then the failed rows keep state, course_no, credit - with NO code
    failed = [i for i in items if i.state == "失敗"]
    assert {(i.course_no, i.code) for i in failed} == {("CSE530", None), ("CSE729", None)}
    by_no = {i.course_no: i for i in failed}
    assert by_no["CSE530"].name == "專題研究（一）"
    assert by_no["CSE530"].credit == 3
    assert by_no["CSE530"].points_priority is None  # cell is &nbsp;
    assert by_no["CSE729"].teacher == "邱勝敏"
    assert by_no["CSE729"].year_semest_note == "期"


# ---------- 登記加選 (absent from the live fixture; synthetic real-layout row) ----------


def _synthetic_real_layout_page(state_cell: str, name: str, teacher: str) -> str:
    """Minimal page mirroring the live 14-column structure cell-for-cell."""
    return f"""<html><head><title>學生課表 Course Schedule</title></head><body>
<table border=1><tr><td>選上與否</td></tr>
<TR><td colspan=14>※ ※  選上課程  ※ ※</td></TR>
<tr><td><p><small>{state_cell}</small></p></td><td><small>資工碩</small></td>
<td><small>CSE540</small></td><td><small>1</small></td><td><small>M3046401</small></td>
<td><small><a href=x>{name}</a></small></td><td><small>15</small></td>
<td><small>22</small></td><td><small>3</small></td><td><small>期</small></td>
<td><small>選</small></td><td><small>{teacher}</small></td>
<td><small>二2,3,4(工EC 3001) </small></td><td><small>&nbsp;</small></td></TR>
</table></body></html>"""


def test_registration_state_row_parses_with_hkscs_text_intact():
    # Given a real-layout 登記加選 row carrying HKSCS-only characters
    page = _synthetic_real_layout_page("登記加選", "雲端運算喆", "黃國堃")
    # When parsed
    (item,) = parse_slt_result(page)
    # Then state, points and the CJK text all survive (decode layer owns
    # big5hkscs; the parser passes decoded text through byte-intact)
    assert item.state == "登記加選"
    assert item.code == "M3046401" and item.course_no == "CSE540"
    assert item.name == "雲端運算喆" and item.teacher == "黃國堃"
    assert item.points_priority == 15 and item.stage == "22"
    assert item.times == "二2,3,4" and item.room == "工EC 3001"


# ---------- fused 教室 split safety ----------


def test_unfused_or_odd_room_text_never_crashes_and_splits_nothing():
    page = _synthetic_real_layout_page("選上", "X", "Y")
    for room_cell, expect_split in (
        ("三2,3,4(工EC 5012)", True),      # canonical fused shape
        ("一2,3,4(工EC 5000) 二1(工EC 100)", False),  # two sessions: no safe split
        ("未定", False),
        ("1056", False),                   # provisional-style bare periods
        ("三2,3,4", False),                # time without room parens
        ("", False),
    ):
        html = page.replace("二2,3,4(工EC 3001) ", room_cell)
        (item,) = parse_slt_result(html)
        assert (item.times is not None) is expect_split, room_cell
        assert (item.room is not None) is expect_split, room_cell
        if expect_split:
            assert item.times == "三2,3,4" and item.room == "工EC 5012"
        else:
            assert item.room_text == room_cell.strip() or room_cell == ""


# ---------- dead session / unrecognized shape ----------


def test_login_page_bounce_is_classified_expired_not_empty():
    for loginish in (
        "<html><body><p>請先登錄</p></body></html>",
        # The school login page itself (SSO2 form markup)
        '<html><body><form action="Studcheck_sso2.asp"><input name="SPassword">'
        "</form></body></html>",
    ):
        with pytest.raises(SelcrsSessionExpired):
            parse_slt_result(loginish)


def test_unrecognized_shape_is_unavailable_never_silently_empty():
    with pytest.raises(SelcrsUnavailable):
        parse_slt_result("<html><body>totally different page</body></html>")


# ---------- provisional 7-column layout (marked variant) ----------


@pytest.mark.provisional
def test_provisional_layout_parses_as_marked_variant():
    # Given the superseded provisional fixture (7 cols, declared big5)
    raw = (FIXTURES / "slt_result_provisional.html").read_bytes()
    items = parse_slt_result(decode_body(raw, None))
    # Then all three rows parse; the provisional failure wording folds to 失敗
    assert len(items) == 3
    assert Counter(item.state for item in items) == {"選上": 1, "登記加選": 1, "失敗": 1}
    selected = next(i for i in items if i.state == "選上")
    assert selected.name == "程式設計（一）" and selected.credit == 3
    assert selected.compulsory_elective == "必修" and selected.teacher == "王喆明"
    # provisional rows have no 課號/課程代碼; 上課時間 goes to room_text raw
    assert selected.code is None and selected.course_no is None
    assert selected.room_text == "1056" and selected.times is None
