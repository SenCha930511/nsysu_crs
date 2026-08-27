"""The redis.asyncio subset the auth subsystem needs (tests substitute a fake).

String values only (the real client is built with ``decode_responses=True``),
second-precision TTLs, plus the sorted-set trio the sliding failure log uses.
Keeping the surface this small is what lets the state machines be tested
deterministically offline (tests/fake_redis.py + injectable clocks).
"""

from typing import Protocol


class AuthRedis(Protocol):
    """Structural type: ``redis.asyncio.Redis`` satisfies this unchanged."""

    async def get(self, name: str) -> str | None: ...

    async def getdel(self, name: str) -> str | None: ...

    async def set(
        self, name: str, value: str, *, nx: bool = False, ex: int | None = None
    ) -> object: ...

    async def delete(self, *names: str) -> int: ...

    async def incr(self, name: str) -> int: ...

    async def rpush(self, name: str, *values: str) -> int: ...

    async def expire(self, name: str, time: int, *, nx: bool = False) -> bool: ...

    async def zadd(self, name: str, mapping: dict[str, float]) -> int: ...

    async def zremrangebyscore(self, name: str, min: float, max: float) -> int: ...

    async def zcard(self, name: str) -> int: ...
