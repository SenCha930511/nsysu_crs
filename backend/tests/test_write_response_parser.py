"""ssprs/saddstage5prs response parser tests (plan todo 15).

ALL fixtures here are synthetic and marked ``provisional`` — the school's
real ssprs reply has NOT been captured yet (todo-4 capture window
2026-08-28 09:00+ is pending as of writing). The contract under test is the
never-guess posture: verdicts come out keyed by course code, ambiguity and
absence degrade to parse_failed with the raw excerpt, and a login bounce is
a session error, never an outcome.
"""

from pathlib import Path

import pytest

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
