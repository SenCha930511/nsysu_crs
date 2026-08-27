"""Response decoding policy for the school system.

Every text response from selcrs/NSYSU is traditional Chinese in Big5, BUT
real teacher/student names occasionally contain HKSCS-only characters
(e.g. "喆") that plain ``big5`` cannot round-trip - decoding them as strict
big5 raises, and encoding them for round-trips was historically the source
of silent corruption. We therefore decode with ``big5hkscs`` everywhere.

Error policy: ``errors='replace'`` for DISPLAY strings. A capture-recorded
mojibake position becomes U+FFFD instead of an exception, so one bad byte in
a 30k-row catalog page never kills an ingest round. Binary payloads
(validcode BMPs) are never decoded at all.
Full writeup: docs/verified-facts.md (Big5-HKSCS decoding policy).
"""

from typing import Final

SELCRS_TEXT_ENCODING: Final = "big5hkscs"


def decode_body(raw: bytes) -> str:
    """Decode a school text response; never raises on bad bytes (replace)."""
    return raw.decode(SELCRS_TEXT_ENCODING, errors="replace")
