"""Backoff contract: transport failures wait exactly [1,2,4,8,16]s over
5 attempts, then raise SelcrsUnavailable; any success ends the loop early."""

import httpx
import pytest

import app.selcrs.http as adapter_http
from app.selcrs.endpoints import get_studfun
from app.selcrs.errors import SelcrsUnavailable
from app.selcrs.http import build_client, request_school
from tests.conftest import StubTransport


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _AlwaysTimeout(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.attempts = 0
        super().__init__()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.attempts += 1
        raise httpx.ConnectTimeout("simulated school outage", request=request)


@pytest.mark.anyio
async def test_five_transport_failures_wait_exactly_1_2_4_8_16_then_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a school that times out on every attempt + a wait recorder
    transport = _AlwaysTimeout()
    waits: list[float] = []

    async def record_wait(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(adapter_http, "_sleep", record_wait)

    # When one adapter call runs to exhaustion
    with pytest.raises(SelcrsUnavailable):
        await get_studfun(httpx.Cookies(), transport=transport)

    # Then 5 attempts fired and the recorded wait list is the contract's
    assert transport.attempts == 5
    assert waits == [1.0, 2.0, 4.0, 8.0, 16.0]


@pytest.mark.anyio
async def test_success_after_failures_stops_backoff_early(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a school failing twice, then answering
    state = {"attempts": 0}

    async def flaky(request: httpx.Request) -> httpx.Response:
        state["attempts"] += 1
        if state["attempts"] <= 2:
            raise httpx.ConnectTimeout("transient", request=request)
        return httpx.Response(200, content=b"<html>recovered</html>")

    transport = StubTransport(flaky)
    waits: list[float] = []

    async def record_wait(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(adapter_http, "_sleep", record_wait)

    # When the request runs
    async with build_client(transport=transport) as client:
        response = await request_school(
            client, "GET", "https://selcrs.nsysu.edu.tw/menu4/Studfun.asp"
        )

    # Then it retried only until success (two waits, three total attempts)
    assert response.status_code == 200
    assert state["attempts"] == 3
    assert waits == [1.0, 2.0]


@pytest.mark.anyio
async def test_http_level_failures_are_not_retried_by_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given a school answering with a hard HTTP-level error
    state = {"attempts": 0}

    async def server_error(request: httpx.Request) -> httpx.Response:
        state["attempts"] += 1
        return httpx.Response(500, content=b"boom")

    transport = StubTransport(server_error)

    # When the request runs, the 500 cannot be a transport retry trigger
    async with build_client(transport=transport) as client:
        response = await request_school(
            client, "GET", "https://selcrs.nsysu.edu.tw/menu4/Studfun.asp"
        )

    # Then exactly one attempt fired - business/HTTP belongs to callers
    assert state["attempts"] == 1
    assert response.status_code == 500
