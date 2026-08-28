"""School circuit breaker (plan todo 8 consume-side; site-wide hardening lands in todo 17).

A streak of ``BREAKER_FAILURE_THRESHOLD`` consecutive unclassifiable school
responses (SSO2 UNKNOWN verdicts and transport failures, both surfaced as
``SelcrsUnavailable``) OPENS the breaker. While open:

- ``admit()`` returns False: the login endpoint answers 503 LOCALLY without
  any school contact and WITHOUT feeding the streak again (no secondary
  feedback loop). Read-only site paths are unaffected by design.

Recovery: once ``BREAKER_RECOVERY_AFTER`` seconds have passed since the last
open-stamp, the next caller probes half-open — exactly one request is let
through per minute (``probe`` gate, ``SET NX EX 60``) while everyone else is
still locally 503. A coherent school answer (SUCCESS or CREDENTIAL-FAIL —
both prove the host speaks its protocol) closes the breaker fully; another
UNKNOWN re-stamps the open instant and the wait restarts.

Streak hygiene: any COHERENT response resets the streak; the streak key
decays at ``2 * recovery_after`` so a half-forgotten blip cannot combine with
next week's outage into a phantom streak.
"""

import time
import uuid
from collections.abc import Callable
from typing import Final

from app.auth.redis_iface import AuthRedis
from app.config import Settings

STREAK_KEY: Final = "breaker:school:streak"
OPENED_AT_KEY: Final = "breaker:school:opened_at"
PROBE_KEY: Final = "breaker:school:probe"
PROBE_GATE_SECONDS: Final = 60


class SchoolBreaker:
    """Streak + open-stamp state machine. Clock is injectable for tests."""

    def __init__(
        self,
        redis: AuthRedis,
        *,
        failure_threshold: int,
        recovery_after: int,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._redis: Final = redis
        self.failure_threshold: Final = failure_threshold
        self.recovery_after: Final = recovery_after
        self._now: Final = now

    async def admit(self) -> bool:
        """True iff the caller may contact the school right now.

        False means: serve a LOCAL 503 - no school call, no streak feedback.
        """
        opened_at = await self._redis.get(OPENED_AT_KEY)
        if opened_at is None:
            return True
        if self._now() - float(opened_at) < self.recovery_after:
            return False
        # Half-open: exactly one probe per gate window; the rest stay local.
        granted = await self._redis.set(
            PROBE_KEY, uuid.uuid4().hex, nx=True, ex=PROBE_GATE_SECONDS
        )
        return bool(granted)

    async def record_classified(self) -> None:
        """School answered coherently (SUCCESS or CREDENTIAL-FAIL): reset all."""
        await self._redis.delete(STREAK_KEY, OPENED_AT_KEY, PROBE_KEY)

    async def record_unknown(self) -> int:
        """Feed one UNKNOWN/transport failure; open at threshold. Returns the streak."""
        streak = await self._redis.incr(STREAK_KEY)
        await self._redis.expire(STREAK_KEY, 2 * self.recovery_after)
        if streak >= self.failure_threshold:
            # Timestamped (not TTL-bound): the recovery wait measures from the
            # LAST unknown, so a still-failing probe restarts the wait here.
            await self._redis.set(OPENED_AT_KEY, repr(self._now()))
            await self._redis.delete(PROBE_KEY)
        return streak


def build_breaker(redis: AuthRedis, settings: Settings) -> SchoolBreaker:
    """The env-knob-wired breaker every school-touching API handler shares."""
    return SchoolBreaker(
        redis,
        failure_threshold=settings.breaker_failure_threshold,
        recovery_after=settings.breaker_recovery_after,
    )
