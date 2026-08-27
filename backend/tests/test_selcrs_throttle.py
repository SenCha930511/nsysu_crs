"""Throttle contract: global cap 2 for school requests, captcha lane 1,
plus per-run cookie-jar isolation for concurrent captcha fetchers."""

import functools

import anyio
import httpx
import pytest

from app.selcrs.endpoints import fetch_validcode, get_slt_result
from tests.conftest import StubTransport


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _ConcurrencyProbe(StubTransport):
    """Counts simultaneous in-flight handler executions; each stays a while."""

    def __init__(self, *, body: bytes = b"<html>ok</html>", dwell: float = 0.03) -> None:
        self.active = 0
        self.max_active = 0
        self._body = body
        self._dwell = dwell
        super().__init__(self._serve)

    async def _serve(self, request: httpx.Request) -> httpx.Response:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await anyio.sleep(self._dwell)
            return httpx.Response(200, content=self._body)
        finally:
            self.active -= 1


@pytest.mark.anyio
async def test_global_school_requests_never_exceed_two_concurrent() -> None:
    # Given six concurrent ordinary school requests
    transport = _ConcurrencyProbe()

    # When they all run at once through the adapter's global lane
    async with anyio.create_task_group() as tasks:
        for _ in range(6):
            tasks.start_soon(
                functools.partial(get_slt_result, httpx.Cookies(), transport=transport)
            )

    # Then in-flight overlap stayed within the cap of 2 (school host fragility)
    assert transport.max_active <= 2


@pytest.mark.anyio
async def test_captcha_parented_requests_are_fully_serialized() -> None:
    # Given three concurrent captcha fetches (three independent catalog runs)
    transport = _ConcurrencyProbe(body=b"BM-fake-bitmap")

    # When they race in the captcha lane (semaphore of 1)
    async with anyio.create_task_group() as tasks:
        for _ in range(3):
            tasks.start_soon(lambda: fetch_validcode(transport=transport))

    # Then the lane never let two overlap
    assert transport.max_active == 1


@pytest.mark.anyio
async def test_concurrent_validcode_runs_get_isolated_jars() -> None:
    # Given a school that issues a per-response unique session cookie
    issued_sequence = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        issued_sequence["n"] += 1
        unique = issued_sequence["n"]
        await anyio.sleep(0.01)
        return httpx.Response(
            200,
            headers={"Set-Cookie": f"ASPSESSION=run{unique}; path=/"},
            content=b"BM-fake-bitmap",
        )

    transport = StubTransport(handler)

    # When two catalog runs fetch captchas concurrently (no jar passed = fresh)
    async with anyio.create_task_group() as tasks:
        result_boxes: list = [None, None]
        for index in range(2):

            async def fetch(idx: int) -> None:
                result_boxes[idx] = await fetch_validcode(transport=transport)

            tasks.start_soon(fetch, index)

    first, second = result_boxes

    # Then each got its own jar object and its own cookie value (no bleed-over)
    assert first.cookies is not second.cookies
    first_value = first.cookies.get("ASPSESSION")
    second_value = second.cookies.get("ASPSESSION")
    assert first_value is not None and second_value is not None
    assert first_value != second_value
