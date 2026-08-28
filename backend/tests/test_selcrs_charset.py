"""Per-response charset resolution unit tests (app/selcrs/decode.py).

Precedence (docs/verified-facts.md, 2026-08-27 live-verified finding):
(1) Content-Type charset param when present and sane,
(2) <meta> charset declaration inside the first META_SCAN_BYTES of the body,
(3) strict-UTF-8 heuristic with big5hkscs fallback.
A declared ``big5`` always upgrades to big5hkscs (superset; HKSCS names).
"""

from app.selcrs.decode import META_SCAN_BYTES, decode_body, resolve_charset


def _big5_page(meta: str | None = None, text: str = "課程系統公告") -> bytes:
    """A Big5-era page: bytes that strict UTF-8 cannot decode."""
    head = f"<html><head>{meta or ''}</head>".encode("ascii")
    return head + f"<body>{text}</body></html>".encode("big5hkscs")


def test_header_charset_wins_over_meta_declaration() -> None:
    # Given a body declaring utf-8 but a header declaring big5
    raw = _big5_page(meta='<meta charset="utf-8">')

    # When the charset is resolved with the header present
    charset = resolve_charset(raw, "text/html; charset=big5")

    # Then transport metadata outranks the body (big5 -> big5hkscs upgrade)
    assert charset == "big5hkscs"


def test_header_charset_wins_over_heuristic() -> None:
    # Given big5 bytes (strict UTF-8 would fail) but a utf-8 header
    raw = _big5_page()

    # When resolved with the header
    # Then the declared charset is trusted, heuristic never runs
    assert resolve_charset(raw, "TEXT/HTML; CHARSET=UTF-8") == "utf-8"


def test_unsane_header_charset_falls_through_to_meta() -> None:
    # Given a header with a garbage charset label and a utf-8 meta in-body
    raw = b'<html><head><meta charset="utf-8"></head><body>x</body></html>'

    # When resolved
    # Then the unsane header is skipped and the meta declaration wins
    assert (
        resolve_charset(raw, "text/html; charset=definitely-not-a-codec") == "utf-8"
    )


def test_header_without_charset_param_falls_through_to_meta() -> None:
    # Given a bare text/html header and a big5 meta declaration
    raw = _big5_page(
        meta='<meta http-equiv="Content-Type" content="text/html; charset=big5">'
    )

    # When resolved
    # Then the meta declares the charset (-> big5hkscs upgrade)
    assert resolve_charset(raw, "text/html") == "big5hkscs"


def test_meta_declaration_wins_when_header_absent() -> None:
    # Given big5 bytes whose meta declares utf-8 (declaration outranks bytes)
    raw = _big5_page(meta='<meta http-equiv="Content-Type" content="text/html; charset=utf-8">')

    # When resolved without a header
    # Then the declared charset is honored even though strict UTF-8 would fail
    assert resolve_charset(raw) == "utf-8"


def test_meta_scan_is_case_insensitive_and_quote_tolerant() -> None:
    # Given an upper-case, single-quoted, Big5-declaring meta
    raw = _big5_page(meta="<META CHARSET='Big5'>")

    # When resolved
    # Then it is found and upgraded to big5hkscs
    assert resolve_charset(raw) == "big5hkscs"


def test_meta_beyond_scan_window_is_ignored() -> None:
    # Given a meta declaration pushed past the scan window by ASCII padding
    pad = " " * (META_SCAN_BYTES + 64)
    raw = (
        "<html><head>"
        + pad
        + '</head><meta charset="big5"><body>課程</body></html>'
    ).encode("utf-8")

    # When resolved
    # Then the late meta is not consulted; the strict-UTF-8 heuristic decides
    assert resolve_charset(raw) == "utf-8"


def test_heuristic_selects_utf8_for_undeclared_utf8_bytes() -> None:
    # Given undeclared CJK UTF-8 bytes (tonight's live login/read pages shape)
    raw = "<html><body>學號碼密碼不符，請重新登錄！</body></html>".encode()

    # When resolved with no header and no meta
    # Then strict UTF-8 succeeds and wins
    assert resolve_charset(raw) == "utf-8"


def test_heuristic_falls_back_to_big5hkscs_for_undeclared_big5_bytes() -> None:
    # Given undeclared Big5-era bytes (invalid as strict UTF-8)
    raw = _big5_page()

    # When resolved with no header and no meta
    # Then the legacy fallback applies
    assert resolve_charset(raw) == "big5hkscs"


def test_declared_big5_is_upgraded_and_hkscs_only_names_survive() -> None:
    # Given an HKSCS-only name character under a plain-big5 header declaration
    snippet = "教師姓名含罕用字「喆」"
    raw = f"<html><body>{snippet}</body></html>".encode("big5hkscs")

    # When decoded through the resolver via the single decode entry point
    decoded = decode_body(raw, "text/html; charset=big5")

    # Then big5 upgraded to big5hkscs: the name round-trips losslessly
    assert snippet in decoded


def test_decode_body_honours_declared_utf8_exactly() -> None:
    # Given the live failure phrase as UTF-8 bytes with a utf-8 declaration
    phrase = "資料錯誤﹕學號碼密碼不符，請重新登錄！"
    raw = phrase.encode("utf-8")

    # When decoded
    # Then the text survives byte-exactly (no mojibake, no replacement)
    assert decode_body(raw, "text/html; charset=utf-8") == phrase


def test_ascii_only_body_is_utf8_by_subset() -> None:
    # Given an all-ASCII/empty body with no declaration
    # When resolved
    # Then ASCII (a UTF-8 subset) resolves utf-8 and decodes harmlessly
    assert resolve_charset(b"") == "utf-8"
    assert resolve_charset(b"<html></html>") == "utf-8"
