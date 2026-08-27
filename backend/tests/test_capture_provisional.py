"""Every provisional fixture exists, decodes as big5hkscs and is marker-stamped."""

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
MARKER = "<!-- provisional: synthetic, replace after 115-1 live capture -->"

PROVISIONAL_FIXTURES = [
    "studfun_open_provisional.html",
    "studfun_closed_provisional.html",
    "ssform_provisional.html",
    "saddstage5_provisional.html",
    "slt_result_provisional.html",
    "dply_page1_provisional.html",
]


@pytest.mark.parametrize("name", PROVISIONAL_FIXTURES)
def test_provisional_fixture_is_marked_on_first_line(name: str) -> None:
    # Given the provisional fixture file
    path = FIXTURES_DIR / name
    assert path.is_file(), f"missing provisional fixture {name}"

    # When decoded per the school-wide encoding policy (big5hkscs)
    text = path.read_bytes().decode("big5hkscs")

    # Then the first line carries the exact provisional marker
    assert text.splitlines()[0] == MARKER
