"""Outline parser tests (per-click syllabus feature, 2026-08-28).

All fixtures are synthetic shapes derived from the real CSE515 outline
capture taken today (UTF-8, label/field lines, numeric-entity CJK).
"""

from pathlib import Path

from app.catalog.outline import parse_outline

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_identity_fields_and_semester_title():
    outline = parse_outline(_load("outline_cse515_synth.html"))
    assert outline.name_zh == "高等電腦網路"
    assert outline.code == "CSE515"
    assert outline.name_en == "ADVANCED COMPUTER NETWORKS"
    assert outline.course_type == "講授類"
    assert outline.requirement == "必修"
    assert outline.dept == "資訊工程學系碩士班"
    assert outline.instructor == "林俊宏"
    assert outline.credit == "3"
    assert outline.semester_title is not None
    assert "115學年度第1學期" in outline.semester_title
    assert "高等電腦網路課程大綱" in outline.semester_title


def test_free_text_sections_decode_numeric_entities_and_stop_at_labels():
    outline = parse_outline(_load("outline_cse515_synth.html"))
    assert outline.syllabus is not None
    assert "之一。" in outline.syllabus  # &#20043;&#19968;&#12290;
    assert "TCP/IP" in outline.syllabus
    assert outline.objectives is not None
    assert "ISO MODEL" in outline.objectives
    assert outline.teaching_methods == "講授"  # &#35611;&#25480;
    # evaluation starts AFTER its duplicated sub-header / terminator line
    assert outline.evaluation is not None
    assert "期中考" in (outline.evaluation or "")
    assert "等第制" not in (outline.evaluation or "")
    assert outline.references is not None
    assert "Stevens" in (outline.references or "")


def test_sparse_foreign_page_yields_none_not_garbage():
    outline = parse_outline("<html><body>Cannot find this outline. NODATA!!</body></html>")
    assert outline.name_zh is None
    assert outline.syllabus is None


def test_malformed_html_never_raises():
    outline = parse_outline("<td>@@@@@@@@@@@@@@@")
    assert outline.name_zh is None
    assert outline.semester_title is None
    br_separated = parse_outline("<td>中文名稱<br>高等電")
    assert br_separated.name_zh == "高等電"
