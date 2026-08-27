"""big5hkscs decoding policy (docs/verified-facts.md): HKSCS-only characters
such as 「喆」must never crash decoding; bad bytes degrade to U+FFFD."""

import pytest

from app.selcrs.decode import SELCRS_TEXT_ENCODING, decode_body

_HKSCS_SNIPPET = "選課系統公告：教師姓名含罕用字「喆」"


def test_hkscs_only_character_round_trips_without_crash() -> None:
    # Given a school HTML fragment containing an HKSCS-only name character
    raw = _HKSCS_SNIPPET.encode("big5hkscs")

    # When the adapter decodes it (the only decode path the app uses)
    # Then it decodes losslessly - no exception, no replacement
    assert decode_body(raw) == _HKSCS_SNIPPET


def test_adapter_policy_is_big5hkscs_not_plain_big5() -> None:
    # Given the adapter's declared encoding
    # Then it is big5hkscs (plain big5 cannot even ENCODE 「喆」)
    assert SELCRS_TEXT_ENCODING == "big5hkscs"
    with pytest.raises(UnicodeEncodeError):
        _HKSCS_SNIPPET.encode("big5")


def test_bad_bytes_degrade_to_replacement_char_and_decoding_continues() -> None:
    # Given a body with a byte run that is invalid in big5hkscs mid-stream
    garbage = "前段".encode("big5hkscs") + b"\x80\xff" + "後段".encode("big5hkscs")

    # When decoded under the replace policy
    decoded = decode_body(garbage)

    # Then no exception, a U+FFFD at the bad site, surrounding text intact
    assert "\ufffd" in decoded
    assert decoded.startswith("前段")
    assert decoded.endswith("後段")
