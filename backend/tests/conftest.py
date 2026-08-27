"""Shared test machinery for selcrs adapter tests (mock school transport)."""

from collections.abc import Awaitable, Callable

import httpx

RequestHandler = Callable[[httpx.Request], Awaitable[httpx.Response]]


class StubTransport(httpx.AsyncBaseTransport):
    """Scriptable async transport: routes every request to the given handler."""

    def __init__(self, handler: RequestHandler) -> None:
        self._handler = handler
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return await self._handler(request)
