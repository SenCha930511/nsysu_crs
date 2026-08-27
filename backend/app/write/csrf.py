"""CSRF double-submit-cookie guard for /api/write/* (plan todo 14).

Contract (plan todo 14 References, verbatim):

- Cookie ``csrf_{session_id}``, httpOnly + Secure + SameSite=Lax, TTL
  CSRF_TOKEN_TTL (900s default), set at login and rotated on every fresh
  login (a new site session means a new cookie NAME and a new random value);
  removed at logout.
- Every ``/api/write/*`` request must repeat the cookie's value in the
  ``X-CSRF-Token`` header; missing/mismatch -> flat 403 ``csrf_failed``.
- Success re-sets the cookie with a fresh 900s TTL (sliding refresh - the
  write flow's preview -> modal -> confirm chain must not die of the
  15-minute cookie clock mid-way).

Because the cookie is httpOnly (plan-pinned), the first-party SPA cannot
read it from JS; the value is therefore ALSO returned in the login response
body (``csrf_token``) - a same-origin channel a cross-site attacker cannot
read - and kept in memory by the client at login. The token never enters
logs, Postgres, or any response beyond that one login body.

The cookie NAME embeds the (unguessable) site session id, so an attacker
cannot toss a known-name cookie from a sibling context to force the pair to
match. Server-side storage is not needed: double-submit compares cookie vs
header (hmac.compare_digest; a timing oracle on the token buys nothing but
the constant-time compare is free).

Ordering: this middleware runs BEFORE the auth dependency, so a request
with no session cookie at all gets 403 csrf_failed (not 401) - write
endpoints are never reachable pre-login anyway.
"""

import hmac
import secrets
from collections.abc import Awaitable, Callable
from typing import Final

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.auth.sessions import SESSION_COOKIE_NAME

CSRF_HEADER: Final = "X-CSRF-Token"
ERR_CSRF: Final = "csrf_failed"
_WRITE_PREFIX: Final = "/api/write/"


def csrf_cookie_name(session_id: str) -> str:
    return f"csrf_{session_id}"


def mint_csrf_token() -> str:
    """A fresh opaque token (login + rotation)."""
    return secrets.token_urlsafe(32)


def set_csrf_cookie(response: Response, session_id: str, token: str, *, ttl: int) -> None:
    """The one place the CSRF cookie's flags are set (login/set + slide)."""
    response.set_cookie(
        csrf_cookie_name(session_id),
        token,
        path="/",
        max_age=ttl,
        secure=True,
        httponly=True,
        samesite="lax",
    )


class CsrfMiddleware(BaseHTTPMiddleware):
    """Double-submit enforcement on /api/write/* only; reads never gated."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if not request.url.path.startswith(_WRITE_PREFIX):
            return await call_next(request)
        session_id = request.cookies.get(SESSION_COOKIE_NAME)
        expected = None
        if session_id:
            expected = request.cookies.get(csrf_cookie_name(session_id))
        provided = request.headers.get(CSRF_HEADER)
        if (
            session_id is None
            or expected is None
            or provided is None
            or not hmac.compare_digest(expected, provided)
        ):
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN, content={"detail": ERR_CSRF}
            )
        response = await call_next(request)
        # Sliding refresh on success: same value, fresh 900s (CSRF_TOKEN_TTL).
        set_csrf_cookie(
            response,
            session_id,
            expected,
            ttl=request.app.state.settings.csrf_token_ttl,
        )
        return response
