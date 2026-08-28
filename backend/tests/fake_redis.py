"""Deterministic in-memory AuthRedis fake (auth tests).

String and sorted-set stores share one keyspace (a second type overwrites the
first, mirroring Redis' WRONGTYPE-free key replacement). TTL arithmetic rides
the SAME injectable clock the state machines under test use, so time-driven
semantics (15-min lock, 1h IP buckets, breaker recovery, session TTLs) are
asserted with zero sleeping.
"""

import time
from collections.abc import Callable


class FakeRedis:
    def __init__(self, now: Callable[[], float] = time.time) -> None:
        self._now = now
        self._values: dict[str, tuple[str, float | None]] = {}
        self._zsets: dict[str, dict[str, float]] = {}
        self._lists: dict[str, list[str]] = {}

    # -- introspection helpers (tests only; not part of AuthRedis) ----------

    def remaining_ttl(self, name: str) -> int | None:
        self._purge(name)
        if name in self._values:
            expire_at = self._values[name][1]
            # round(): int() flaked - sub-second time.time() jitter read 604800 as 604799.
            return None if expire_at is None else round(expire_at - self._now())
        return None

    def keys_with_prefix(self, prefix: str) -> list[str]:
        for key in list(self._values):
            self._purge(key)
        keys = [k for k in self._values if k.startswith(prefix)]
        keys.extend(k for k in self._lists if k.startswith(prefix))
        return sorted(keys)

    def lmembers(self, name: str) -> list[str]:
        """Synchronous list read for assertions (mirrors LRANGE 0 -1)."""
        return list(self._lists.get(name, []))

    def peek(self, name: str) -> str | None:
        """Synchronous string read for assertions (mirrors GET sans TTL side effects)."""
        self._purge(name)
        entry = self._values.get(name)
        return entry[0] if entry is not None else None

    def zmembers(self, name: str) -> dict[str, float]:
        return dict(self._zsets.get(name, {}))

    def zcount_peek(self, name: str) -> int:
        return len(self._zsets.get(name, {}))

    # -- TTL machinery ------------------------------------------------------

    def _purge(self, name: str) -> None:
        entry = self._values.get(name)
        if entry is not None and entry[1] is not None and entry[1] <= self._now():
            del self._values[name]

    # -- AuthRedis surface --------------------------------------------------

    async def get(self, name: str) -> str | None:
        self._purge(name)
        entry = self._values.get(name)
        return entry[0] if entry is not None else None

    async def getdel(self, name: str) -> str | None:
        self._purge(name)
        entry = self._values.pop(name, None)
        return entry[0] if entry is not None else None

    async def set(
        self, name: str, value: str, *, nx: bool = False, ex: int | None = None
    ) -> object:
        self._purge(name)
        if nx and name in self._values:
            return None
        expire_at = None if ex is None else self._now() + ex
        self._values[name] = (value, expire_at)
        self._zsets.pop(name, None)
        self._lists.pop(name, None)
        return True

    async def incr(self, name: str) -> int:
        self._purge(name)
        entry = self._values.get(name)
        value = (int(entry[0]) if entry is not None else 0) + 1
        expire_at = entry[1] if entry is not None else None
        self._values[name] = (str(value), expire_at)
        return value

    async def rpush(self, name: str, *values: str) -> int:
        self._values.pop(name, None)
        listing = self._lists.setdefault(name, [])
        listing.extend(values)
        return len(listing)

    async def lrange(self, name: str, start: int, end: int) -> list[str]:
        listing = self._lists.get(name, [])
        stop = None if end == -1 else end + 1
        return list(listing[start:stop])

    async def llen(self, name: str) -> int:
        return len(self._lists.get(name, []))

    async def brpop(self, keys: list[str], timeout: int = 0) -> list[str] | None:
        for key in keys:
            listing = self._lists.get(key)
            if listing:
                return [key, listing.pop()]
        return None

    async def delete(self, *names: str) -> int:
        removed = 0
        for name in names:
            removed += int(self._values.pop(name, None) is not None)
            removed += int(self._zsets.pop(name, None) is not None)
            removed += int(self._lists.pop(name, None) is not None)
        return removed

    async def expire(self, name: str, seconds: int, *, nx: bool = False) -> bool:
        self._purge(name)
        if name in self._values:
            value, expire_at = self._values[name]
            if nx and expire_at is not None:
                return False
            self._values[name] = (value, self._now() + seconds)
            return True
        if name in self._zsets:
            return not nx
        return False

    async def zadd(self, name: str, mapping: dict[str, float]) -> int:
        self._values.pop(name, None)
        zset = self._zsets.setdefault(name, {})
        added = sum(1 for member in mapping if member not in zset)
        zset.update(mapping)
        return added

    async def zremrangebyscore(self, name: str, min: float, max: float) -> int:
        zset = self._zsets.get(name, {})
        doomed = [m for m, score in zset.items() if min <= score <= max]
        for member in doomed:
            del zset[member]
        return len(doomed)

    async def zcard(self, name: str) -> int:
        return len(self._zsets.get(name, {}))
