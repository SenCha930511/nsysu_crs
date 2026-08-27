"""Pure-helper tests for the live kit: form scraping + byte-exact body building."""

from scripts.capture.formparse import (
    build_submit_body,
    find_write_link,
    looks_like_login_page,
    scrape_form,
)

_FORM_HTML = """
<html><body>
<a href="querys.asp">課程查詢</a>
<a href="ssform.asp?X1=09&X2=0&DEG_COD=B">加退選課程</a>
<form name="f1" method="post" action="ssprs.asp">
<input type="hidden" name="step" value="2">
<input type="hidden" name="X1" value="09">
<input type="hidden" name="D1" value="N">
<input type="text" name="C1" size="8">
<input type="submit" name="send" value="提交">
</form>
</body></html>
"""


def test_scrape_form_collects_links_actions_and_hidden_in_document_order() -> None:
    # Given a Studfun-style form page
    scrape = scrape_form(_FORM_HTML)

    # Then every href, form action and hidden input is captured, in order
    assert scrape.links == ["querys.asp", "ssform.asp?X1=09&X2=0&DEG_COD=B"]
    assert scrape.form_actions == ["ssprs.asp"]
    assert scrape.hidden == [("step", "2"), ("X1", "09"), ("D1", "N")]


def test_find_write_link_picks_the_add_drop_form_link() -> None:
    assert find_write_link(scrape_form(_FORM_HTML)) == "ssform.asp?X1=09&X2=0&DEG_COD=B"


def test_find_write_link_accepts_stage5_variant() -> None:
    html = '<a href="stage5/saddstage5.asp?X1=01">初選登記</a>'
    assert find_write_link(scrape_form(html)) == "stage5/saddstage5.asp?X1=01"


def test_find_write_link_none_when_window_closed() -> None:
    assert find_write_link(scrape_form('<a href="querys.asp">查詢</a>')) is None


def test_build_submit_body_replays_hidden_and_overrides_byte_exactly() -> None:
    # Given hidden inputs plus the D/C/send overrides for a real ADD
    body = build_submit_body(
        [("step", "2"), ("X1", "09"), ("D1", "N")],
        [("D1", "+"), ("C1", "12345678"), ("send", "提交")],
    )

    # Then the override wins over the same-named hidden input, order is
    # stable, '+' is escaped and the Chinese submit value is Big5-encoded
    # (提=%B4%A3, 交=%A5%E6) - byte-identical to a browser on the Big5 page.
    assert body == "step=2&X1=09&D1=%2B&C1=12345678&send=%B4%A3%A5%E6"


def test_build_submit_body_is_deterministic_for_verbatim_replay() -> None:
    hidden = [("step", "2"), ("X1", "09")]
    overrides = [("D1", "+"), ("C1", "12345678"), ("send", "提交")]
    assert build_submit_body(hidden, overrides) == build_submit_body(hidden, overrides)


def test_looks_like_login_page_detects_sso2_form_markers() -> None:
    assert looks_like_login_page('<form><input name="SPassword"></form>')
    assert looks_like_login_page('<meta refresh url="Studcheck_sso2.asp">')
    assert not looks_like_login_page("<html>選課結果清單</html>")
