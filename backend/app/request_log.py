"""Request access log (plan todo 17): request-id + one JSON line per request.

Every request gets an id (the incoming ``X-Request-ID`` is honored up to 64
chars - a correlation aid from our own Caddy; anything longer/garbage is
replaced with a fresh uuid4), echoed back on the ``X-Request-ID`` response
header, and one line is emitted on the ``app.access`` logger whose MESSAGE is
a single JSON object:

    {"ts", "request_id", "method", "path", "status", "latency_ms"}

Under uvicorn the root handler prints ``INFO:     {...json...}`` - the JSON
is the whole message, so line-scrapers split on the first ``{``.

PII/secret contract (grep-tested): the line carries NO body bytes, NO query
string (``request.url.path`` only), NO headers (so no Cookie/Authorization/
X-CSRF-Token), NO client IP. ``/api/auth/*`` and ``/api/write/*`` bodies
never appear anywhere; the login password is a SecretStr unwrapped once at
the adapter call, far from this middleware.

Exceptions: a handler that raises past the exception handlers is still
logged, as status 500, before the traceback propagates to uvicorn's
ServerErrorMiddleware (which sits outside all custom middleware).
"""

import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Final
from zoneinfo import ZoneInfo

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

ACCESS_LOGGER: Final = "app.access"
REQUEST_ID_HEADER: Final = "X-Request-ID"
_MAX_INCOMING_ID: Final = 64

logger: Final = logging.getLogger(ACCESS_LOGGER)


def configure_access_log() -> None:
    """Give ``app.access`` a stdout handler so the lines exist under uvicorn.

    uvicorn configures only its own loggers; an unconfigured INFO logger with
    no handlers anywhere up the logger chain silently drops records.
    Propagation stays enabled so pytest's caplog (root-attached) still
    captures records.
    Idempotent: create_app runs once per process, tests call it repeatedly.
    """
    if not any(isinstance(handler, logging.StreamHandler) for handler in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)


class RequestLogMiddleware(BaseHTTPMiddleware):
    """Outermost app middleware (added last): one JSON line per request."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER)
        request_id = (
            incoming
            if incoming is not None and 0 < len(incoming) <= _MAX_INCOMING_ID
            else uuid.uuid4().hex
        )
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
        finally:
            latency_ms = round((time.perf_counter() - started) * 1000, 1)
            tz = ZoneInfo(request.app.state.settings.tz)
            logger.info(
                "%s",
                json.dumps(
                    {
                        "ts": datetime.now(tz).isoformat(timespec="milliseconds"),
                        "request_id": request_id,
                        "method": request.method,
                        "path": request.url.path,
                        "status": status_code,
                        "latency_ms": latency_ms,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
