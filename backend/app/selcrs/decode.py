"""Per-response charset resolution for the school system.

Policy (2026-08-27; supersedes the original all-big5hkscs assumption - see
docs/verified-facts.md, "Big5-HKSCS decoding policy" plus the live-verified
(115-1) encoding finding):

Selcrs pages are NOT uniformly Big5-era anymore. Tonight's live capture
proved the login/read pages (``Studcheck_sso2.asp``, ``Studfun.asp``,
``query/slt_result.asp``) are UTF-8 on the wire, while catalog-era endpoints
may still be Big5. Decoding everything as big5hkscs mis-decodes the UTF-8
pages into mojibake and - observed against the real failure fixture - flips
a genuine SSO2 CREDENTIAL-FAIL into UNKNOWN (breaker path). Charset is
therefore resolved PER RESPONSE by ``resolve_charset``, in strict precedence:

1. The ``charset`` parameter of the Content-Type header, when present and
   sane (``codecs.lookup`` succeeds). Transport metadata outranks bytes.
2. A ``charset`` declaration inside the first ``META_SCAN_BYTES`` (2 KiB) of
   the body (both ``<meta charset=...>`` and the http-equiv Content-Type
   form). The declaration itself is ASCII, so the scan runs on raw bytes and
   works for undecodable Big5-era pages too.
3. Heuristic: a strict UTF-8 decode attempt over the whole body -> ``utf-8``
   on success (all-ASCII bodies land here harmlessly, ASCII being a UTF-8
   subset), else ``big5hkscs``.

Normalization rule: a declared ``big5`` (or any alias that ``codecs.lookup``
canonicalizes to ``big5``, e.g. ``big-5``, ``csbig5``) is UPGRADED to
``big5hkscs`` - HKSCS occupies only code space that Big5 leaves undefined, so
the superset decodes every true-Big5 byte identically while surviving
HKSCS-only teacher/student name characters (e.g. 「喆」) that plain ``big5``
cannot even encode.

Error policy (unchanged): ``decode_body`` decodes with ``errors='replace'``,
so one bad byte degrades to U+FFFD at that position instead of killing a
30k-row catalog ingest. Binary payloads (validcode BMPs) are never decoded.
"""

import codecs
import re
from typing import Final

SELCRS_TEXT_ENCODING: Final = "big5hkscs"

# Declared charsets are honored only inside this many leading body bytes -
# far enough to cover any <head>, small enough that a stray late "charset"
# string in page content cannot hijack decoding.
META_SCAN_BYTES: Final = 2048

_HEADER_CHARSET_RE: Final = re.compile(
    r"charset\s*=\s*[\"']?\s*([A-Za-z0-9._-]+)", re.IGNORECASE
)
_META_CHARSET_RE: Final = re.compile(
    rb"charset\s*=\s*[\"']?\s*([A-Za-z0-9._-]+)", re.IGNORECASE
)


def _lookup(label: str) -> str | None:
    """Canonical codec name for a sane charset label, else None."""
    try:
        return codecs.lookup(label).name
    except LookupError:
        return None


def _upgrade_big5(charset: str) -> str:
    """Map a resolved ``big5`` label to big5hkscs (superset; see module doc)."""
    if charset == "big5":
        return SELCRS_TEXT_ENCODING
    return charset


def resolve_charset(raw: bytes, content_type: str | None = None) -> str:
    """Pick the decode charset for ONE response (precedence in module doc)."""
    if content_type is not None:
        header_hit = _HEADER_CHARSET_RE.search(content_type)
        if header_hit is not None:
            charset = _lookup(header_hit.group(1))
            if charset is not None:
                return _upgrade_big5(charset)
    meta_hit = _META_CHARSET_RE.search(raw[:META_SCAN_BYTES])
    if meta_hit is not None:
        charset = _lookup(meta_hit.group(1).decode("ascii"))
        if charset is not None:
            return _upgrade_big5(charset)
    try:
        raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return SELCRS_TEXT_ENCODING
    return "utf-8"


def decode_body(raw: bytes, content_type: str | None = None) -> str:
    """Decode one school text response; never raises on bad bytes (replace).

    ``content_type`` is the response's Content-Type header value when the
    caller has one (adapter call-sites pass it); omitted callers get the
    meta/heuristic branches of the same policy.
    """
    return raw.decode(resolve_charset(raw, content_type), errors="replace")
