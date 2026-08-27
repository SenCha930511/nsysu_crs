"""base64md5 transform tests - locked to NsysuApp behaviour via pinned vectors.

Vectors were generated with the Dart-original semantics
(base64(md5(text).raw_digest_bytes), standard padded Base64) and verified
against openssl; the same 3 vectors are recorded in docs/verified-facts.md
with the source commit sha. See app/selcrs/transform.py.
"""

import pytest

from app.selcrs.transform import base64md5

# (input, base64(md5(input))) - vectors verified beyond this repo by running
# `printf %s "<input>" | openssl md5 -binary | openssl base64`.
BASE64MD5_VECTORS: tuple[tuple[str, str], ...] = (
    ("123456", "4QrcOUm6Wau+VuBX8g+IPg=="),
    ("654321", "wzNncBURtPYCDsYd7TUgWQ=="),
    ("", "1B2M2Y8AsgTpgAmY7PhCfg=="),
)


@pytest.mark.parametrize(("plain", "expected"), BASE64MD5_VECTORS)
def test_base64md5_matches_the_three_pinned_vectors(plain: str, expected: str) -> None:
    # Given a pinned input from docs/verified-facts.md
    # When the transform runs
    # Then it equals the openssl-verified Base64 of the raw MD5 digest
    assert base64md5(plain) == expected


def test_base64md5_uses_raw_digest_bytes_not_hex_string() -> None:
    # Given "123456": md5 hex is e10adc3949ba59abbe56e057f20f883e
    # If implementation base64-encoded the HEX STRING instead of raw digest
    # bytes, output would be "ZTEwYWRjMzk0OWJhNTlhYmJlNTZlMDU3ZjIwZjg4M2U="
    result = base64md5("123456")
    assert result != "ZTEwYWRjMzk0OWJhNTlhYmJlNTZlMDU3ZjIwZjg4M2U="
    assert result == "4QrcOUm6Wau+VuBX8g+IPg=="


def test_base64md5_utf8_encodes_cjk_before_hashing() -> None:
    # Given a CJK string: Dart utf8.encode(text) -> Python text.encode("utf-8")
    # must agree byte-exactly (vector re-derived from openssl for this string)
    # `printf %s "密碼" | openssl md5 -binary | openssl base64` -> ZmLISKgMMMjQQr/RfPWuLA==
    assert base64md5("密碼") == "ZmLISKgMMMjQQr/RfPWuLA=="
