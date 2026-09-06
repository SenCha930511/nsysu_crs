"""Feature-parser tests (M1) - every assertion pinned to a live M0 fixture."""

from pathlib import Path

import pytest

from app.selcrs.errors import SelcrsUnavailable
from app.stuenroll.parse import (
    parse_payment_bills,
    parse_regweb_checklist,
    parse_sco_menu,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_payment_page_parses_dept_and_the_twd_bill() -> None:
    page = parse_payment_bills(_load("stuenroll_payment_live_1151.html"))
    assert page.dept == "資訊工程學系碩士班"
    assert len(page.bills) == 1
    bill = page.bills[0]
    assert bill.item == "1151學雜費"
    assert bill.amount.startswith("14,155")
    assert bill.status == "繳費成功"
    assert bill.pay_date == "2026/08/31"
    assert bill.receipt_href == "tfstudata.asp?act=61&mst_sno=IM1151006292"


def test_sco_menu_frame_parses_all_feature_links() -> None:
    links = parse_sco_menu(_load("stuenroll_grades_frame_0_live_1151.html"))
    assert len(links) >= 4
    by_title = {link.title: link for link in links}
    history = by_title["歷年成績查詢"]
    assert history.action == "811"
    assert history.kind == "3"
    assert "學期成績查詢" in by_title
    assert "學生預警成績查詢" in by_title


def test_regweb_checklist_parses_items_and_enrollcert_flag() -> None:
    checklist = parse_regweb_checklist(_load("stuenroll_regweb_main_live_1151.html"))
    assert checklist.enrollcert_present is True
    titles = [item.title for item in checklist.items]
    assert any("確認個人基本資料" in title for title in titles)
    confirm = next(item for item in checklist.items if "確認個人基本資料" in item.title)
    assert "已完成" in confirm.status_text
    assert confirm.out_url is not None and "verify_stuasp" not in confirm.out_url


def test_drift_raises_instead_of_guessing() -> None:
    with pytest.raises(SelcrsUnavailable):
        parse_payment_bills("<html><body>404</body></html>")
    with pytest.raises(SelcrsUnavailable):
        parse_sco_menu("<html><body>no anchors</body></html>")
    with pytest.raises(SelcrsUnavailable):
        parse_regweb_checklist("<html><body>no relays</body></html>")
