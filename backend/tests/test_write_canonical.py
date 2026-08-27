"""Canonical idempotency spec tests (plan todos 14/15, QA qa/14-*.log part).

The plan pins the exact rule (todo 15 ``canonical 規格``): sort by
(action order -,+,N then code asc), collapse consecutive identical
(action,code), T stripped for '-', zero-padded 2 for '+', string
``student_no|act:code:TT|...``, sha256. The plan's own two permutations must
hash identically - locked here as the strongest regression anchor for the
todo-15 submission engine that consumes this module UNCHANGED.
"""

import re

import pytest

from app.write.canonical import (
    CanonicalOp,
    canonical_ops,
    canonical_segments,
    canonical_string,
    confirm_token,
    payload_hash,
)

STUDENT = "M153000024"
SECRET = "qa14-test-secret"


def test_plan_permutations_produce_identical_canonical_hash():
    # Given the two operator orderings the plan names explicitly
    first = [CanonicalOp("+", "12345678", 1), CanonicalOp("-", "87654321")]
    second = [CanonicalOp("-", "87654321"), CanonicalOp("+", "12345678", 1)]

    # When canonicalized
    # Then both land on the same string and hence the same sha256
    assert canonical_string(STUDENT, canonical_ops(first)) == canonical_string(
        STUDENT, canonical_ops(second)
    )
    assert canonical_string(STUDENT, canonical_ops(first)) == (
        "M153000024|-:87654321:|+:12345678:01"
    )
    assert payload_hash(STUDENT, canonical_ops(first)) == payload_hash(
        STUDENT, canonical_ops(second)
    )
    assert confirm_token(STUDENT, canonical_ops(first), secret=SECRET) == confirm_token(
        STUDENT, canonical_ops(second), secret=SECRET
    )


def test_sort_key_is_action_order_then_code():
    ops = canonical_ops(
        [
            CanonicalOp("+", "GEAE2526", 2),
            CanonicalOp("+", "AAAA0001", 1),
            CanonicalOp("N", "ZZZZ9999"),
            CanonicalOp("-", "BBBB0002"),
        ]
    )
    assert [(op.action, op.code) for op in ops] == [
        ("-", "BBBB0002"),
        ("+", "AAAA0001"),
        ("+", "GEAE2526"),
        ("N", "ZZZZ9999"),
    ]


def test_consecutive_identical_action_code_pairs_collapse_first_wins():
    ops = canonical_ops(
        [
            CanonicalOp("+", "GEAE2526", 3),
            CanonicalOp("+", "GEAE2526", 7),
            CanonicalOp("-", "M3046243"),
            CanonicalOp("-", "M3046243"),
        ]
    )
    assert canonical_segments(ops) == "-:M3046243:|+:GEAE2526:03"


def test_drop_strips_priority_and_add_zero_pads():
    ops = canonical_ops([CanonicalOp("+", "GEAE2526", 5), CanonicalOp("-", "M3046243")])
    assert canonical_segments(ops) == "-:M3046243:|+:GEAE2526:05"
    double_digit = canonical_ops([CanonicalOp("+", "GEAE2526", 20)])
    assert canonical_segments(double_digit) == "+:GEAE2526:20"


def test_canonical_string_is_student_prefixed_segments():
    ops = canonical_ops([CanonicalOp("+", "GEAE2526", 1)])
    assert canonical_string("B123456789", ops) == "B123456789|+:GEAE2526:01"
    assert canonical_string("B123456789", []) == "B123456789|"


def test_confirm_token_shape_and_secrecy():
    ops = canonical_ops([CanonicalOp("+", "GEAE2526", 1)])
    token = confirm_token(STUDENT, ops, secret=SECRET)
    # base64url alphabet, padding stripped (token is a Redis key component)
    assert re.fullmatch(r"[A-Za-z0-9_\-]+", token)
    assert "=" not in token
    assert len(token) == 43  # 32 bytes -> ceil(256/6) chars
    assert confirm_token(STUDENT, ops, secret="other-secret") != token
    assert confirm_token("B999999999", ops, secret=SECRET) != token
    assert confirm_token(STUDENT, canonical_ops([CanonicalOp("+", "GEAE2526", 2)]), secret=SECRET) != token


def test_payload_hash_is_sha256_hex():
    ops = canonical_ops([CanonicalOp("+", "GEAE2526", 1)])
    digest = payload_hash(STUDENT, ops)
    assert re.fullmatch(r"[0-9a-f]{64}", digest)


def test_invalid_ops_rejected_at_the_boundary():
    with pytest.raises(ValueError, match="unknown action"):
        CanonicalOp("x", "GEAE2526")
    with pytest.raises(ValueError, match="add ops carry a priority"):
        CanonicalOp("+", "GEAE2526")
    with pytest.raises(ValueError, match="never carry a priority"):
        CanonicalOp("-", "GEAE2526", 1)
