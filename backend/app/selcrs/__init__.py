"""selcrs adapter package: the only HTTP path to the school system.

Public surface. Guardrail (enforced by tests): everything under
``backend/app/`` outside this package MUST NOT import httpx directly - all
school traffic goes through this boundary so throttling, redirects, TLS and
decoding policies hold globally.
"""

from app.selcrs.decode import SELCRS_TEXT_ENCODING, decode_body, resolve_charset
from app.selcrs.endpoints import (
    SELCRS_BASE_URL,
    CatalogQuery,
    Sso2Result,
    ValidcodeResult,
    fetch_catalog_page,
    fetch_validcode,
    get_slt_result,
    get_studfun,
    get_write_form,
    login_sso2,
    post_write,
)
from app.selcrs.errors import SelcrsError, SelcrsUnavailable
from app.selcrs.http import build_client, build_school_ssl_context, request_school
from app.selcrs.sso2 import Sso2Outcome
from app.selcrs.transform import base64md5

__all__ = [
    "SELCRS_BASE_URL",
    "SELCRS_TEXT_ENCODING",
    "CatalogQuery",
    "SelcrsError",
    "SelcrsUnavailable",
    "Sso2Outcome",
    "Sso2Result",
    "ValidcodeResult",
    "base64md5",
    "build_client",
    "build_school_ssl_context",
    "decode_body",
    "fetch_catalog_page",
    "fetch_validcode",
    "get_slt_result",
    "get_studfun",
    "get_write_form",
    "login_sso2",
    "post_write",
    "request_school",
    "resolve_charset",
]
