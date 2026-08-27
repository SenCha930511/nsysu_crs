"""qrycourse YRSM discovery tests (plan todo 6)."""

import pytest

from app.catalog.discover import DiscoveryError, parse_d0_options, pick_current_d0

_PAGE = """
<html><body>
<select id="YRSM" name="YRSM">
  <option value="1132">113學年度第2學期</option>
  <option value="1141">114學年度第1學期</option>
  <option value="1142">114學年度第2學期</option>
  <option value="1151" selected>115學年度第1學期</option>
  <option value="">全部</option>
</select>
</body></html>
"""


def test_options_extracted_in_document_order():
    assert parse_d0_options(_PAGE) == ("1132", "1141", "1142", "1151")


def test_preselected_option_wins_when_present():
    assert pick_current_d0(_PAGE) == "1151"


def test_max_code_wins_when_nothing_preselected():
    unselected = _PAGE.replace(" selected", "")
    assert pick_current_d0(unselected) == "1151"


def test_text_only_options_are_read_from_label():
    html = '<select id="YRSM"><option>1142</option><option>1151</option></select>'
    assert pick_current_d0(html) == "1151"


def test_missing_select_raises_discovery_error():
    with pytest.raises(DiscoveryError):
        pick_current_d0("<html><body>no form</body></html>")


def test_select_without_numeric_options_raises():
    with pytest.raises(DiscoveryError):
        parse_d0_options('<select id="YRSM"><option value="">全部</option></select>')
