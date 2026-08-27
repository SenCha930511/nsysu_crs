"""SSO2 password transform: base64(md5(password)).

Byte-exact port of NsysuApp ``Utils.base64md5``.

Adapted from NsysuApp_OpenSource (MIT License, Copyright (c) 2026 Edwin Chu):
https://raw.githubusercontent.com/edwinchu0711/NsysuApp_OpenSource/fe64ddb64df76614fc406a7ec2b6694af26c75d6/lib/utils/utils.dart

Dart original:

    static String base64md5(String text) {
      var bytes = utf8.encode(text);       // 1. UTF-8 encode
      var digest = md5.convert(bytes);     // 2. MD5 -> raw 16 bytes
      return base64.encode(digest.bytes);  // 3. std Base64 of RAW digest bytes
    }

i.e. base64(md5(text)), where the MD5 output is the 16-byte raw digest
(NOT the 32-char hex string) and Base64 is the standard alphabet with
padding. Test vectors live in docs/verified-facts.md and tests.
"""

import base64
import hashlib


def base64md5(text: str) -> str:
    """Return Base64(standard, padded) of the raw MD5 digest of utf8(text)."""
    digest = hashlib.md5(text.encode("utf-8"), usedforsecurity=False).digest()
    return base64.b64encode(digest).decode("ascii")
