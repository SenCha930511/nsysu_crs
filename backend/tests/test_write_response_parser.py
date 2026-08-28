"""ssprs/saddstage5prs response parser tests (plan todo 15).

The ``*_provisional`` fixtures stay synthetic and marked provisional (the
archaeological row-table expectation, not live-verified). The CANONICAL
fixture is ``ssprs_resp_addfail_live_1151``: the real ssprs reply recorded
2026-08-28 in the 115-1 加退選一 window - a status snapshot whose
【加退選失敗課程清單】 section rejects the batch-level op without itemizing
codes. The contract under test is the never-guess posture: verdicts come
out keyed by course code, ambiguity and absence degrade to parse_failed
with the raw excerpt, and a login bounce is a session error, never an
outcome.
"""

from pathlib import Path

import pytest

from app.selcrs.decode import decode_body
from app.selcrs.errors import SelcrsSessionExpired
from app.write.outcomes import OUTCOME_FAILED, OUTCOME_PARSE_FAILED, OUTCOME_SUCCESS
from app.write.response import (
    EXCERPT_LIMIT,
    classify_fragment,
    is_session_bounce,
    parse_submit_response,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _load_live(name: str) -> str:
    """Raw bytes through the adapter's per-response charset policy."""
    return decode_body((FIXTURES / name).read_bytes())


BATCH = ["M3046243", "GEAE2526", "MEME101B"]


def test_all_ok_maps_success_to_the_right_codes():
    parsed = parse_submit_response(_load("ssprs_resp_all_ok_provisional.html"), BATCH)
    assert {code: parsed[code].outcome for code in BATCH} == {
        "M3046243": OUTCOME_SUCCESS,
        "GEAE2526": OUTCOME_SUCCESS,
        "MEME101B": OUTCOME_SUCCESS,
    }
    assert all(not parsed[code].duplicate_like for code in BATCH)
    assert "退選成功" in (parsed["M3046243"].school_msg or "")


def test_mixed_verdicts_map_by_code_not_row_order():
    # 3 ops: ok / 額滿 / 必修-violation -> mapped back to the right codes.
    parsed = parse_submit_response(_load("ssprs_resp_mixed_provisional.html"), BATCH)
    assert parsed["GEAE2526"].outcome == OUTCOME_SUCCESS
    assert parsed["MEME101B"].outcome == OUTCOME_FAILED
    assert "額滿" in (parsed["MEME101B"].school_msg or "")
    assert parsed["M3046243"].outcome == OUTCOME_FAILED
    assert "必修" in (parsed["M3046243"].school_msg or "")
    # none of these failure vocabularies is duplicate-like
    assert not parsed["MEME101B"].duplicate_like
    assert not parsed["M3046243"].duplicate_like


def test_duplicate_like_failure_is_flagged():
    parsed = parse_submit_response(
        _load("ssprs_resp_dup_provisional.html"), ["GEAE2526", "MEME101B"]
    )
    assert parsed["GEAE2526"].outcome == OUTCOME_FAILED
    assert parsed["GEAE2526"].duplicate_like is True  # 重複加選
    assert parsed["MEME101B"].outcome == OUTCOME_SUCCESS


def test_drift_page_yields_parse_failed_with_excerpt_never_guessed():
    parsed = parse_submit_response(_load("ssprs_resp_drift_provisional.html"), BATCH)
    for code in BATCH:
        assert parsed[code].outcome == OUTCOME_PARSE_FAILED
        excerpt = parsed[code].school_msg or ""
        assert excerpt  # raw excerpt stored
        assert len(excerpt) <= EXCERPT_LIMIT


def test_a_code_absent_from_the_page_is_parse_failed_with_page_excerpt():
    parsed = parse_submit_response(_load("ssprs_resp_all_ok_provisional.html"), ["ZZ999999"])
    assert parsed["ZZ999999"].outcome == OUTCOME_PARSE_FAILED
    assert "加退選處理結果" in (parsed["ZZ999999"].school_msg or "")


def test_non_tabular_lines_still_key_by_code():
    html = (
        "<html><body>處理結果："
        "<p>GEAE2526 加選成功</p>"
        "<p>MEME101B 加選失敗：衝堂</p>"
        "</body></html>"
    )
    parsed = parse_submit_response(html, ["GEAE2526", "MEME101B"])
    assert parsed["GEAE2526"].outcome == OUTCOME_SUCCESS
    assert parsed["MEME101B"].outcome == OUTCOME_FAILED


def test_ambiguous_fragment_is_parse_failed_never_guessed():
    verdict = classify_fragment("<td>GEAE2526 加選成功 但 MEME101B 加選失敗</td>")
    assert verdict.outcome == OUTCOME_PARSE_FAILED


def test_failure_wording_containing_success_shape_is_not_a_success():
    verdict = classify_fragment("<td>MEME101B 加選不成功</td>")
    assert verdict.outcome == OUTCOME_PARSE_FAILED  # 成功 substring + 不成功: ambiguous


def test_login_bounce_raises_session_expired_and_is_detected():
    bounce = "<html><body>請先登錄</body></html>"
    assert is_session_bounce(bounce)
    with pytest.raises(SelcrsSessionExpired):
        parse_submit_response(bounce, BATCH)


# ---------- canonical live fixture (recorded 2026-08-28, 115-1 加退選一) ----------


def test_live_addfail_fixture_maps_business_failure_with_school_message():
    parsed = parse_submit_response(_load_live("ssprs_resp_addfail_live_1151.html"), ["ZZ999999"])
    verdict = parsed["ZZ999999"]
    assert verdict.outcome == OUTCOME_FAILED
    assert not verdict.duplicate_like  # no per-op duplicate wording on the page
    assert "加退選失敗課程清單" in (verdict.school_msg or "")
    # The 回加退選課程 back-link is navigation, not a school message.
    assert "回加退選課程" not in (verdict.school_msg or "")


def test_live_fixture_selections_snapshot_is_never_consulted():
    # CSE515 sits in the page's 【目前選課紀錄】 table (the user's real,
    # pre-existing selection). A batch mentioning it must still key on the
    # failure section, never on the snapshot rows.
    parsed = parse_submit_response(
        _load_live("ssprs_resp_addfail_live_1151.html"), ["ZZ999999", "CSE515"]
    )
    for code in ("ZZ999999", "CSE515"):
        assert parsed[code].outcome == OUTCOME_FAILED
        assert "加退選失敗課程清單" in (parsed[code].school_msg or "")
        assert "選上" not in (parsed[code].school_msg or "")  # no snapshot-row bleed


def test_itemized_code_inside_failure_section_classifies_its_own_fragment():
    # Synthetic section content under the LIVE header: when the school does
    # itemize an op, the fragment rules (never the wholesale fallback).
    html = (
        "<html><body>"
        "<p>【加退選失敗課程清單】</p>"
        "<p>MEME101B 加選失敗：名額已滿（額滿）</p>"
        '<a href="ssform.asp">回加退選課程</a>'
        "</body></html>"
    )
    parsed = parse_submit_response(html, ["MEME101B", "ZZ999999"])
    assert parsed["MEME101B"].outcome == OUTCOME_FAILED
    assert "額滿" in (parsed["MEME101B"].school_msg or "")
    assert parsed["ZZ999999"].outcome == OUTCOME_FAILED  # wholesale fallback
    assert "MEME101B" not in (parsed["ZZ999999"].school_msg or "")


def test_duplicate_wording_without_failure_marker_still_fails_duplicate_like():
    # A bare 重複/已選 rejection (no 「失敗」 beside it) is a rejection: failed
    # + duplicate_like so a transport-retried op lands unknown-reconciled.
    html = "<html><body>處理結果：<p>GEAE2526 重複加選</p></body></html>"
    parsed = parse_submit_response(html, ["GEAE2526"])
    assert parsed["GEAE2526"].outcome == OUTCOME_FAILED
    assert parsed["GEAE2526"].duplicate_like is True


# ---------- rule-based per-op rows (synthetic-from-live-audit, 2026-08-28) ----------


def test_rule_failure_is_failed_by_section_membership_with_full_reason():
    # Section membership IS the verdict: the real AI50015 row carries the
    # multi-line reason with zero failure-marker vocabulary.
    parsed = parse_submit_response(
        _load("ssprs_resp_limitation_fail_synth_1151.html"), ["AI50015"]
    )
    verdict = parsed["AI50015"]
    assert verdict.outcome == OUTCOME_FAILED
    assert "違反限修條件" in (verdict.school_msg or "")
    assert "prerequisites" in (verdict.school_msg or "")


def test_raw_student_no_is_masked_in_every_stored_school_msg():
    # The fixture id echoes raw on the school's page; storage must mask it.
    parsed = parse_submit_response(
        _load("ssprs_resp_limitation_fail_synth_1151.html"), ["AI50015"]
    )
    msg = parsed["AI50015"].school_msg or ""
    assert "M153000024" not in msg
    assert "M153****24" in msg


def test_excerpt_cap_keeps_full_policy_sentence_bounded_at_500():
    assert EXCERPT_LIMIT == 500
    html = (
        "<html><body>【加退選失敗課程清單】<p>GEAE2526 "
        + "。違反限修條件X" * 200
        + '</p><a href="ssform.asp">回加退選課程</a></body></html>'
    )
    parsed = parse_submit_response(html, ["GEAE2526"])
    msg = parsed["GEAE2526"].school_msg or ""
    assert len(msg) <= EXCERPT_LIMIT
    assert parsed["GEAE2526"].outcome == OUTCOME_FAILED
