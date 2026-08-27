"""HTTP boundary for the NSYSU course-selection system (selcrs).

This module is the ONLY place the adapter talks to the school. All adapter
httpx usage goes through ``build_client`` + ``request_school`` so the
following invariants cannot drift per call-site:

- ``follow_redirects=False`` pinned globally: a 302 is a MEANINGFUL signal on
  this system (SSO2 success redirect to main_frame); silently following it
  would destroy the tri-state login classification.
- Legacy TLS: the school's classic-ASP front-end requires OpenSSL's legacy
  server-connect path, so every client gets a dedicated SSL context with
  ``OP_LEGACY_SERVER_CONNECT`` and ``DEFAULT@SECLEVEL=1`` injected.
- Throttling: the host is fragile at peak (course-selection windows), so a
  shared process-wide semaphore caps concurrent school requests at 2 - and
  that cap covers EVERY call the adapter makes to the school. Captcha-related
  traffic (validcode fetches and the dplycourse POSTs that spend the solved
  code) additionally funnels through a separate semaphore-of-1, so it is
  fully serialized process-wide while still counting against the global cap;
  each catalog run must also carry a per-run cookie jar (see endpoints.py).
- Transport-level backoff only: TimeoutException/TransportError retry with
  waits of exactly 1, 2, 4, 8, 16s (= 5 attempts), then SelcrsUnavailable.
  HTTP-level outcomes (404/500/unknown bodies) are NOT retried here - they are
  classified by callers, and business-failure retry policy belongs to the
  write engine (todo 15), not the transport.
"""

import ssl
from typing import Final

import anyio
import httpx

from app.selcrs.errors import SelcrsUnavailable

# Observably generous timeouts: the school front-end sits behind a slow
# campus path and goes seconds-slow at selection-window peak. Connect is the
# fragile leg (legacy TLS renegotiation); reads get more room.
CONNECT_TIMEOUT_SECONDS: Final = 10.0
READ_TIMEOUT_SECONDS: Final = 30.0
WRITE_TIMEOUT_SECONDS: Final = 10.0
POOL_TIMEOUT_SECONDS: Final = 30.0

# Backoff contract (plan todo 3): inside the semaphore, attempt, on transport
# failure wait, retry; after the 5th attempt's wait, raise SelcrsUnavailable.
# The recorded wait sequence for a fully-failing request is exactly
# [1, 2, 4, 8, 16] - the final 16s subdivision is part of the contract and is
# asserted by tests/QA.
BACKOFF_SECONDS: Final = (1.0, 2.0, 4.0, 8.0, 16.0)
MAX_ATTEMPTS: Final = len(BACKOFF_SECONDS)

# Process-wide gates. Semaphores are module-level by design: the cap must be
# shared across every concurrent call-site (web request handlers, catalog
# ingest worker runs) to bound total pressure on the school. The captcha
# gate is taken ON TOP of the school gate (never instead of it), so total
# school concurrency stays <= 2 even while captcha traffic is traffic-shaped
# down to 1.
_SCHOOL_SEMAPHORE: Final = anyio.Semaphore(2)
_CAPTCHA_SEMAPHORE: Final = anyio.Semaphore(1)

# Indirection seam so tests can record the wait sequence instantly without
# real sleeping (QA: qa/03-backoff.log asserts the exact sequence).
_sleep = anyio.sleep


def build_school_ssl_context() -> ssl.SSLContext:
    """OpenSSL context for the school's legacy TLS stack.

    ``OP_LEGACY_SERVER_CONNECT`` permits negotiation with servers using the
    pre-RFC5746 renegotiation style; ``DEFAULT@SECLEVEL=1`` lowers the
    security level so the school's aged cipher parameters are accepted.
    Scoped to THIS context only - the rest of the process keeps modern
    defaults.
    """
    context = ssl.create_default_context()
    context.options |= ssl.OP_LEGACY_SERVER_CONNECT
    context.set_ciphers("DEFAULT@SECLEVEL=1")
    return context


def build_client(
    *,
    cookies: httpx.Cookies | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.AsyncClient:
    """Construct an adapter client. Tests inject a mock ``transport``."""
    return httpx.AsyncClient(
        cookies=cookies,
        follow_redirects=False,  # pinned: redirect-as-signal, never follow
        timeout=httpx.Timeout(
            READ_TIMEOUT_SECONDS,
            connect=CONNECT_TIMEOUT_SECONDS,
            write=WRITE_TIMEOUT_SECONDS,
            pool=POOL_TIMEOUT_SECONDS,
        ),
        verify=build_school_ssl_context(),
        transport=transport,
    )


async def request_school(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    captcha_parented: bool = False,
    data: dict[str, str] | None = None,
    params: dict[str, str | int] | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """One school request under throttle + transport-only backoff.

    ``captcha_parented=True`` routes through the semaphore-of-1 lane reserved
    for captcha-related requests (validcode fetches and the dplycourse POSTs
    that spend the solved code; each catalog run carries its own jar and runs
    must never interleave). The captcha lane is taken ON TOP of the global
    school cap of 2, so every call the adapter makes to the school - captcha
    or not - counts against that global cap.
    """
    if captcha_parented:
        async with _CAPTCHA_SEMAPHORE, _SCHOOL_SEMAPHORE:
            return await _request_with_backoff(
                client, method, url, data=data, params=params, headers=headers
            )
    async with _SCHOOL_SEMAPHORE:
        return await _request_with_backoff(
            client, method, url, data=data, params=params, headers=headers
        )


async def _request_with_backoff(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    data: dict[str, str] | None,
    params: dict[str, str | int] | None,
    headers: dict[str, str] | None,
) -> httpx.Response:
    """Attempt loop. Semaphore(s) are held by the caller for the whole loop,
    including backoff waits: a school that is timing out must not be hit by a
    fresh request while another is mid-backoff against it."""
    last_error: httpx.TransportError | None = None
    for wait_seconds in BACKOFF_SECONDS:
        try:
            return await client.request(
                method, url, data=data, params=params, headers=headers
            )
        except httpx.TransportError as exc:
            # Transport-level only: DNS/connect/TLS/timeout/pool issues.
            # (TimeoutException is a subclass of TransportError.)
            last_error = exc
            await _sleep(wait_seconds)
    raise SelcrsUnavailable(
        f"school unreachable after {MAX_ATTEMPTS} transport attempts"
    ) from last_error


__all__ = [
    "BACKOFF_SECONDS",
    "MAX_ATTEMPTS",
    "build_client",
    "build_school_ssl_context",
    "request_school",
    "_sleep",  # test seam (monkeypatch target)
]
