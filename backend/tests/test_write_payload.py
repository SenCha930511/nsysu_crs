"""Payload builder tests (plan todo 14, QA qa/14-replay.log part).

Two proof layers:

1. THE ARCHAEOLOGICAL FIELD TABLE (``.omo/drafts`` key_facts, todo 14
   References): D1..Dn = +/-/N, C1..Cn = 8-char course code, T1..Tn =
   志願 1-20 (points 0-100 stay unreachable: flag-off 初選1), X1/X2/DEG_COD/
   college/dept/grade/SCH_COD/USE_YR/EDU identity params, MAX_ADD (15/10),
   send=提交, step per variant. Every expected key asserted present; D/C/T
   slot math, '-' T-clearing, and T zero-pad vs empty locked.

2. REPLAY INTEGRITY (diff detector, plan: 重放組包對 fixture 之 hidden 全數
   原樣通過): parse the provisional ssform/stage5 fixtures, build, and prove
   every scraped non-D/C/T hidden field passes through byte-identical.
"""

from pathlib import Path

import pytest

from app.write.canonical import CanonicalOp, canonical_ops
from app.write.payload import (
    build_payload_ssprs,
    build_payload_stage5,
    parse_form_hidden_inputs,
    parse_send_value,
)

FIXTURES = Path(__file__).parent / "fixtures"

#: The archaeological identity set both forms must carry (draft key_facts).
IDENTITY_KEYS = {"X1", "X2", "DEG_COD", "college", "dept", "grade", "SCH_COD", "USE_YR", "EDU"}


def ROW_KEYS(n: int) -> set[str]:
    return {f"{c}{i}" for i in range(1, n + 1) for c in "DCT"}


def _hidden(rows: int, **overrides: str) -> dict[str, str]:
    hidden = {
        "step": "2",
        "X1": "09",
        "X2": "0",
        "DEG_COD": "B",
        "college": "1",
        "dept": "36",
        "grade": "1",
        "SCH_COD": "2",
        "USE_YR": "115",
        "EDU": "B",
        "MAX_ADD": str(rows),
        "send": "提交",
    }
    hidden.update(overrides)
    return hidden


SAMPLE_OPS = canonical_ops(
    [
        CanonicalOp("-", "M3046243"),
        CanonicalOp("+", "GEAE2526", 1),
        CanonicalOp("+", "MEME101B", 20),
    ]
)


# ---------- 1. archaeological field table: every expected key + slot math ----------


def test_ssprs_field_table_is_complete_and_verbatim():
    hidden = _hidden(15)
    payload = build_payload_ssprs(SAMPLE_OPS, hidden)
    expected_keys = IDENTITY_KEYS | {"step", "MAX_ADD", "send"} | ROW_KEYS(15)
    assert expected_keys <= set(payload)
    # non-D/C/T fields replay VERBATIM
    for key in IDENTITY_KEYS | {"step", "MAX_ADD", "send"}:
        assert payload[key] == hidden[key]


def test_ssprs_slot_math_drop_add_rest():
    payload = build_payload_ssprs(SAMPLE_OPS, _hidden(15))
    # canonical order: '-' first, then '+' ascending code
    assert (payload["D1"], payload["C1"], payload["T1"]) == ("-", "M3046243", "")
    assert (payload["D2"], payload["C2"], payload["T2"]) == ("+", "GEAE2526", "01")
    assert (payload["D3"], payload["C3"], payload["T3"]) == ("+", "MEME101B", "20")
    for row in range(4, 16):
        assert (payload[f"D{row}"], payload[f"C{row}"], payload[f"T{row}"]) == ("N", "", "")


def test_drop_rows_clear_t_and_zero_pad_vs_empty():
    ops = canonical_ops([CanonicalOp("-", "GEAE2526"), CanonicalOp("+", "M3046243", 7)])
    payload = build_payload_ssprs(ops, _hidden(15))
    assert payload["T1"] == ""  # '-' row: T cleared even though a code exists
    assert payload["T2"] == "07"  # '+' row: zero-padded 2
    assert payload["T3"] == ""  # rest row: empty, never "00"


def test_stage5_field_table_and_ten_slots():
    hidden = _hidden(10, step="1")
    ops = canonical_ops([CanonicalOp("+", "GEAE2526", 7)])
    payload = build_payload_stage5(ops, hidden)
    expected_keys = IDENTITY_KEYS | {"step", "MAX_ADD", "send"} | ROW_KEYS(10)
    assert expected_keys <= set(payload)
    assert payload["step"] == "1"
    assert payload["MAX_ADD"] == "10"
    assert (payload["D1"], payload["C1"], payload["T1"]) == ("+", "GEAE2526", "07")
    assert "D11" not in payload and "C11" not in payload and "T11" not in payload


def test_max_add_from_the_form_sets_the_row_count():
    payload = build_payload_ssprs(SAMPLE_OPS, _hidden(15, MAX_ADD="12"))
    assert "D12" in payload and "D13" not in payload


def test_ops_overflowing_the_form_is_a_hard_error():
    ops = [CanonicalOp("+", f"C{i:07d}", i) for i in range(1, 12)]
    with pytest.raises(ValueError, match="exceed"):
        build_payload_stage5(ops, _hidden(10))


def test_send_preserved_from_scrape_and_defaulted_when_absent():
    assert build_payload_ssprs([], _hidden(15, send="提交"))["send"] == "提交"
    assert build_payload_ssprs([], _hidden(15))["send"] == "提交"
    no_send = _hidden(15)
    no_send.pop("send")
    assert build_payload_ssprs([], no_send)["send"] == "提交"


# ---------- 2. replay integrity over the provisional fixtures ----------


def test_replay_integrity_ssform_fixture_passthrough_byte_identical():
    html = (FIXTURES / "ssform_provisional.html").read_bytes().decode("big5hkscs")
    hidden = parse_form_hidden_inputs(html)
    # the fixture's own hidden set (archaeological table), exactly
    assert hidden == {
        "step": "2", "X1": "09", "X2": "0", "DEG_COD": "B", "college": "1",
        "dept": "36", "grade": "1", "SCH_COD": "2", "USE_YR": "115",
        "EDU": "B", "MAX_ADD": "15",
    }
    assert parse_send_value(html) == "提交"

    payload = build_payload_ssprs(SAMPLE_OPS, hidden | {"send": parse_send_value(html)})
    # every scraped non-D/C/T hidden field passes through UNCHANGED
    for key, value in hidden.items():
        assert payload[key] == value
    assert payload["send"] == "提交"
    # and the ONLY extra keys are the owned D/C/T slots
    assert set(payload) - set(hidden) - {"send"} == ROW_KEYS(15)


def test_replay_integrity_stage5_fixture_passthrough_byte_identical():
    html = (FIXTURES / "saddstage5_provisional.html").read_bytes().decode("big5hkscs")
    hidden = parse_form_hidden_inputs(html)
    assert hidden == {
        "step": "1", "X1": "01", "X2": "0", "DEG_COD": "B", "college": "1",
        "dept": "36", "grade": "1", "SCH_COD": "2", "USE_YR": "115",
        "EDU": "B", "MAX_ADD": "10",
    }
    assert parse_send_value(html) == "提交"

    ops = canonical_ops(
        [CanonicalOp("+", "GEAE2526", 7), CanonicalOp("-", "M3046243")]
    )
    payload = build_payload_stage5(ops, hidden | {"send": parse_send_value(html)})
    for key, value in hidden.items():
        assert payload[key] == value
    assert set(payload) - set(hidden) - {"send"} == ROW_KEYS(10)
    assert (payload["D1"], payload["C1"], payload["T1"]) == ("-", "M3046243", "")
    assert (payload["D2"], payload["C2"], payload["T2"]) == ("+", "GEAE2526", "07")
