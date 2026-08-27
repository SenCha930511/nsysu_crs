"""Error types for the captcha solver service (plan todo 5).

``CaptchaUnsolvable`` is distinct from ``SelcrsUnavailable`` on purpose: the
school host answered fine and rejected our solved codes - that is a SOLVER
accuracy failure, not a school outage. It must therefore NOT feed the circuit
breaker; it feeds the plan's operational gate (per-attempt success-rate p and
the BLOCKED-ON-USER-DECISION end-state) instead.
"""

from typing import Final


class CaptchaUnsolvable(Exception):
    """Retry budget exhausted: the school rejected every solved captcha.

    Terminal state for one catalog page - raised exactly once, after the
    final attempt's wrong-code response. No further retries happen past this
    point for the page (plan todo 5: on the 5th wrong code, raise).
    """

    def __init__(self, *, attempts: int) -> None:
        super().__init__(
            f"catalog captcha still rejected after {attempts} solved attempts"
        )
        self.attempts: Final = attempts
