"""parse_canonical_segments tests (todo 15): the confirm record carries the
segments string only; the submit side re-derives ops + payload_hash."""

import pytest

from app.write.canonical import (
    CanonicalOp,
    canonical_segments,
    parse_canonical_segments,
)


def test_roundtrip_mixed_batch():
    ops = [
        CanonicalOp(action="-", code="M3046243"),
        CanonicalOp(action="+", code="GEAE2526", priority=1),
        CanonicalOp(action="+", code="MEME101B", priority=2),
    ]
    assert parse_canonical_segments(canonical_segments(ops)) == tuple(ops)


def test_parse_zero_padded_priority_returns_int():
    assert parse_canonical_segments("+:GEAE2526:01") == (
        CanonicalOp(action="+", code="GEAE2526", priority=1),
    )


def test_parse_plan_vector_shape():
    # The plan-pinned canonical order: '-' sorts before '+'.
    assert parse_canonical_segments("-:M3046243:|+:GEAE2526:01") == (
        CanonicalOp(action="-", code="M3046243"),
        CanonicalOp(action="+", code="GEAE2526", priority=1),
    )


@pytest.mark.parametrize(
    "segments",
    [
        "X:GEAE2526:",  # unknown action
        "+GEAE2526",  # missing separators
        "+:GEAE2526:",  # add without TT
        "-:M3046243:01",  # non-add carrying TT
        "::",  # empty action/code
        "",  # empty record
    ],
)
def test_malformed_segments_raise(segments):
    with pytest.raises(ValueError):
        parse_canonical_segments(segments)
