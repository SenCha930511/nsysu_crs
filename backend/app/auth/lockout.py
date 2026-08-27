"""Login throttling (plan todo 8): sliding-log account lockout + IP limiter.

FailureLog — per-account sliding failure log in one Redis sorted set:

- Every real CREDENTIAL-FAIL result (and only those) is appended as a member
  whose score is its own expiry instant (``failure_time + window``): each
  failure expires individually 15 minutes after it happened, never in a batch.
  Expired members are pruned lazily on every read/write, so after a lock
  expires the log decays entry-by-entry and an attacker must re-accumulate
  from a clean window.
- When the unexpired count reaches ``fail_limit``, a FIXED lock of
  ``lock_minutes`` is set with ``SET NX EX``: it is written exactly once per
  trigger and never extended. While the lock key exists, callers reject with
  429 BEFORE contacting the school and MUST NOT call ``record_credential_fail``
  (local rejections are not school verdicts and never enter the log).
- A successful login NEVER clears the log (prevents a victim's login
  refunding an attacker's budget).

IpLimiter — secondary fixed clock-hour window: the bucket is part of the key
(``floor(epoch/3600)``), so the window boundary is the wall-clock hour, not a
sliding TTL. Every attempt reaching the login endpoint counts, including
locally-rejected 429s on a locked account (plan-pinned); on campus NAT this
is deliberately loose (dorm-NAT rationale in docs).
"""

import time
import uuid
from collections.abc import Callable
from typing import Final

from app.auth.redis_iface import AuthRedis


def _fail_log_key(student_no: str) -> str:
    return f"loginfail:{student_no}"


def _lock_key(student_no: str) -> str:
    return f"loginlock:{student_no}"


def _ip_key(ip: str, hour_bucket: int) -> str:
    return f"loginip:{ip}:{hour_bucket}"


class FailureLog:
    """Sliding per-account credential-failure log with a fixed, non-extending lock."""

    def __init__(
        self,
        redis: AuthRedis,
        *,
        fail_limit: int,
        lock_minutes: int,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._redis: Final = redis
        self.fail_limit: Final = fail_limit
        self.window_seconds: Final = lock_minutes * 60
        self._now: Final = now

    async def is_locked(self, student_no: str) -> bool:
        """True while the fixed lock key exists (never extended once set)."""
        return await self._redis.get(_lock_key(student_no)) is not None

    async def unexpired_failures(self, student_no: str) -> int:
        """Failures still inside their individual 15-minute windows."""
        key = _fail_log_key(student_no)
        await self._redis.zremrangebyscore(key, float("-inf"), self._now())
        return await self._redis.zcard(key)

    async def record_credential_fail(self, student_no: str) -> bool:
        """Append one real CREDENTIAL-FAIL verdict; lock when budget is spent.

        Returns True iff the account is locked after this append (the lock was
        just triggered by it, or already stood). The lock write is ``NX EX``:
        the first trigger wins and nothing ever extends it.
        """
        key = _fail_log_key(student_no)
        now = self._now()
        await self._redis.zremrangebyscore(key, float("-inf"), now)
        # Unique member per attempt: retries at the same instant never collide.
        await self._redis.zadd(key, {uuid.uuid4().hex: now + self.window_seconds})
        # Key-level TTL is cosmetic (memory hygiene only); effective per-entry
        # expiry lives in the scores, so refreshing it changes no semantics.
        await self._redis.expire(key, self.window_seconds)
        if await self._redis.zcard(key) >= self.fail_limit:
            await self._redis.set(_lock_key(student_no), "1", nx=True, ex=self.window_seconds)
            return True
        return False


class IpLimiter:
    """Fixed clock-hour IP window: INCR a bucketed key, admit while <= limit."""

    def __init__(
        self,
        redis: AuthRedis,
        *,
        hourly_limit: int,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._redis: Final = redis
        self.hourly_limit: Final = hourly_limit
        self._now: Final = now

    async def hit(self, ip: str) -> int:
        """Count this attempt (inclusive) and return the bucket total."""
        key = _ip_key(ip, int(self._now() // 3600))
        count = await self._redis.incr(key)
        # NX: the TTL anchors to bucket creation and is never refreshed.
        await self._redis.expire(key, 3700, nx=True)
        return count

    def admits(self, count: int) -> bool:
        return count <= self.hourly_limit
