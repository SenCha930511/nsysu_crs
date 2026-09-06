"""Post-login fan-out: best-effort login to the two stu_enroll jar families.

Plan §5.2 (方案 A, fail-soft): after the site login's SSO2 SUCCESS, the same
password window funds BOTH subsystem logins (stu_enroll chain -> regweb jar;
sco interactive -> sco jar) under one overall deadline. This module never
raises: every failure degrades that leg to ``available=False`` with a
``LegError`` kind, so a misbehaving subsystem can never block the site login
itself. Breaker policy stays in the API layer - the caller maps LegError
onto record_unknown / record_classified.
"""

import logging
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

import anyio

from app.selcrs.errors import SelcrsUnavailable
from app.selcrs.http import AsyncBaseTransport, Cookies
from app.stuenroll.endpoints import SCO_LOGIN_URL, STU_ENROLL_LOGIN_URL
from app.stuenroll.login import (
    SCO_ROLES,
    STU_ENROLL_ROLES,
    FieldRoles,
    SolveFn,
    interactive_login,
)

_logger = logging.getLogger(__name__)

DEFAULT_FANOUT_TIMEOUT_S: Final = 8.0


class LegError(StrEnum):
    """Why one subsystem leg ended unavailable (breaker taxonomy for callers)."""

    CAPTCHA_BUDGET = "captcha_budget"
    SCHOOL_UNAVAILABLE = "school_unavailable"
    TIMEOUT = "timeout"
    UNEXPECTED = "unexpected"


@dataclass(frozen=True, slots=True)
class FanoutLeg:
    available: bool
    jar: Cookies | None
    error: LegError | None
    attempts: int
    elapsed_s: float


@dataclass(frozen=True, slots=True)
class FanoutResult:
    regweb: FanoutLeg
    sco: FanoutLeg

    @property
    def regweb_available(self) -> bool:
        return self.regweb.available

    @property
    def sco_available(self) -> bool:
        return self.sco.available


async def fanout_subsystem_logins(
    student_id: str,
    password: str,
    *,
    timeout_s: float = DEFAULT_FANOUT_TIMEOUT_S,
    solve: SolveFn | None = None,
    transport: AsyncBaseTransport | None = None,
) -> FanoutResult:
    """Log in to both jar families concurrently; never raises, never blocks
    past ``timeout_s``. A leg missing from the results map after the deadline
    is reported as TIMEOUT - move_on_after swallows its own cancellation, so
    that is the only way a leg goes unfilled.
    """
    results: dict[str, FanoutLeg] = {}

    async def _leg(name: str, roles: FieldRoles, login_url: str) -> None:
        started = time.monotonic()

        def _elapsed() -> float:
            return time.monotonic() - started

        try:
            outcome = await interactive_login(
                student_id,
                password,
                roles=roles,
                login_url=login_url,
                solve=solve,
                transport=transport,
            )
        except SelcrsUnavailable:
            results[name] = FanoutLeg(False, None, LegError.SCHOOL_UNAVAILABLE, 0, _elapsed())
            return
        except Exception:
            _logger.exception("stuenroll fan-out leg %s failed unexpectedly", name)
            results[name] = FanoutLeg(False, None, LegError.UNEXPECTED, 0, _elapsed())
            return
        if outcome.ok and outcome.landing is not None and outcome.landing.cookies is not None:
            results[name] = FanoutLeg(
                True, outcome.landing.cookies, None, outcome.attempts, _elapsed()
            )
            return
        results[name] = FanoutLeg(
            False, None, LegError.CAPTCHA_BUDGET, outcome.attempts, _elapsed()
        )

    with anyio.move_on_after(timeout_s):
        async with anyio.create_task_group() as tg:
            tg.start_soon(_leg, "regweb", STU_ENROLL_ROLES, STU_ENROLL_LOGIN_URL)
            tg.start_soon(_leg, "sco", SCO_ROLES, SCO_LOGIN_URL)
    return FanoutResult(
        regweb=results.get("regweb", FanoutLeg(False, None, LegError.TIMEOUT, 0, timeout_s)),
        sco=results.get("sco", FanoutLeg(False, None, LegError.TIMEOUT, 0, timeout_s)),
    )
