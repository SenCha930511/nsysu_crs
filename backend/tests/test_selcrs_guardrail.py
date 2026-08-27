"""Guardrail: business modules must not import httpx directly.

Only backend/app/selcrs/ may depend on httpx - that boundary pins throttling,
redirects, TLS and decoding globally. This scan fails if any other module
under backend/app/ imports httpx (plan todo 3: 業務碼禁直接 import httpx).
"""

import re
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[1] / "app"
_ADAPT_ROOT = _APP_ROOT / "selcrs"
_IMPORTS_HTTPX = re.compile(r"^\s*(import|from)\s+httpx\b", re.MULTILINE)


def test_no_business_module_imports_httpx_directly() -> None:
    # Given every python module under backend/app EXCEPT the adapter package
    offenders = [
        path.relative_to(_APP_ROOT)
        for path in _APP_ROOT.rglob("*.py")
        if _ADAPT_ROOT not in path.parents and _IMPORTS_HTTPX.search(path.read_text("utf-8"))
    ]

    # When/Then none may import httpx - school IO belongs in app/selcrs only
    assert offenders == []


def test_guardrail_scan_would_catch_an_adapter_level_import() -> None:
    # Given the adapter package itself
    users = [
        path.relative_to(_ADAPT_ROOT)
        for path in _ADAPT_ROOT.rglob("*.py")
        if _IMPORTS_HTTPX.search(path.read_text("utf-8"))
    ]

    # The scan pattern matches there -> the guardrail above is not vacuous
    assert users != []
