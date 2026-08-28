"""The redis.asyncio subset the auth subsystem needs (tests substitute a fake).

String values only (the real client is built with ``decode_responses=True``),
second-precision TTLs, plus the sorted-set trio the sliding failure log uses.
Keeping the surface this small is what lets the state machines be tested
deterministically offline (tests/fake_redis.py + injectable clocks).
"""

from collections.abc import Awaitable
from typing import Protocol


class AuthRedis(Protocol):
    """Structural type: ``redis.asyncio.Redis`` satisfies this unchanged.

    Members are plain ``def``s returning ``Awaitable`` (not ``async def``s
    returning ``Coroutine``) because redis-py's stubs type these methods as
    returning ``Awaitable``; ``Coroutine`` is a subtype of ``Awaitable``, so
    both the real client and async-def fakes satisfy the protocol."""

    def get(self, name: str) -> Awaitable[str | None]: ...

    def getdel(self, name: str) -> Awaitable[str | None]: ...

    def set(
        self, name: str, value: str, *, nx: bool = False, ex: int | None = None
    ) -> Awaitable[object]: ...

    def delete(self, *names: str) -> Awaitable[int]: ...

    def incr(self, name: str) -> Awaitable[int]: ...

    def rpush(self, name: str, *values: str) -> Awaitable[int]: ...

    def expire(self, name: str, time: int, *, nx: bool = False) -> Awaitable[bool]: ...

    def zadd(self, name: str, mapping: dict[str, float]) -> Awaitable[int]: ...

    def zremrangebyscore(self, name: str, min: float, max: float) -> Awaitable[int]: ...

    def zcard(self, name: str) -> Awaitable[int]: ...
