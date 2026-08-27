"""Studfun stage-detection tests (plan todo 13; QA qa/13-stage.log part 1).

Fixture matrix must hold exactly: REAL live closed -> 關閉 (no params),
synthetic open ssform -> 加退選/ssform, synthetic open stage5 -> 初選/stage5,
drift -> 未知 + drift_no_marker (NEVER an exception, never an open stage),
and the 必修課程確認 pre-step form page -> need_confirmation via the two
verbatim edwinchu anchors.
"""

from pathlib import Path

import pytest

from app.selcrs.errors import SelcrsSessionExpired
from app.stage.detect import (
    PRESTEP_ONCLICK_ANCHOR,
    detect_need_confirmation,
    parse_studfun,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str, encoding: str = "utf-8") -> str:
    # New fixtures are UTF-8 (post-encoding-fix live pages); the superseded
    # provisional ones are raw big5 bytes -> decode with big5hkscs there.
    return (FIXTURES / name).read_bytes().decode(encoding)


# ---------- five fixture cases (QA qa/13-stage.log) ----------


def test_real_closed_fixture_reports_closed_without_params() -> None:
    result = parse_studfun(_load("studfun_closed_live_1151.html"))
    assert result.stage == "關閉"
    assert result.variant is None
    assert result.form_href is None
    assert result.params is None
    assert result.reason == "closed_heading"


def test_open_ssform_fixture_reports_add_drop_with_params() -> None:
    result = parse_studfun(_load("studfun_open_ssform_provisional.html"))
    assert result.stage == "加退選"
    assert result.variant == "ssform"
    assert result.reason == "ssform_link"
    assert result.form_href is not None
    assert result.form_href.startswith("addcourse/ssform.asp?")
    assert result.params is not None
    assert result.params.model_dump() == {
        "X1": "09",
        "X2": "0",
        "EDU": "B",
        "DEG_COD": "B",
        "college": "1",
        "dept": "36",
        "grade": "1",
        "SCH_COD": "2",
        "USE_YR": "115",
    }


def test_open_stage5_fixture_reports_first_round_with_params() -> None:
    result = parse_studfun(_load("studfun_open_stage5_provisional.html"))
    assert result.stage == "初選"
    assert result.variant == "stage5"
    assert result.reason == "stage5_link"
    assert result.form_href is not None
    assert result.form_href.startswith("addcourse/stage5/saddstage5.asp?")
    assert result.params is not None
    assert result.params.X1 == "01"
    assert result.params.USE_YR == "115"


def test_drift_fixture_reports_unknown_and_never_an_open_stage() -> None:
    # Misleading 加退選/初選 text alone must not open a window.
    result = parse_studfun(_load("studfun_drift.html"))
    assert result.stage == "未知"
    assert result.variant is None
    assert result.form_href is None
    assert result.params is None
    assert result.reason == "drift_no_marker"


def test_legacy_provisional_closed_fixture_reads_as_readonly_links() -> None:
    # The superseded big5-mojibake provisional closed page: no write link and
    # only query-family hrefs -> still 關閉 (closed_readonly_links branch).
    result = parse_studfun(_load("studfun_closed_provisional.html", "big5hkscs"))
    assert result.stage == "關閉"
    assert result.variant is None
    assert result.reason == "closed_readonly_links"


# ---------- prestep gate (need_confirmation) ----------


def test_prestep_form_fixture_triggers_need_confirmation() -> None:
    assert detect_need_confirmation(_load("ssform_prestep_provisional.html")) is True


def test_normal_form_fixtures_do_not_trigger_need_confirmation() -> None:
    assert detect_need_confirmation(_load("ssform_provisional.html", "big5hkscs")) is False
    assert (
        detect_need_confirmation(_load("saddstage5_provisional.html", "big5hkscs")) is False
    )


def test_prestep_requires_both_anchors_not_button_alone() -> None:
    # The 送出 button WITHOUT the step-injection onclick must not gate.
    html = '<html><body><input type="submit" name="send" value="送出"></body></html>'
    assert PRESTEP_ONCLICK_ANCHOR not in html
    assert detect_need_confirmation(html) is False


# ---------- session expiry ----------


def test_login_page_bounce_raises_session_expired() -> None:
    html = '<html><body><form action="Studcheck_sso2.asp">請先登錄</form></body></html>'
    with pytest.raises(SelcrsSessionExpired):
        parse_studfun(html)
