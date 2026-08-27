"""Error types for the selcrs adapter.

Two disjoint failure classes per plan todo 3:

- ``SelcrsUnavailable``: the school host misbehaved (transport failures after
  backoff, or an SSO2 response matching neither SUCCESS nor CREDENTIAL-FAIL).
  It feeds the circuit breaker and MUST NEVER count toward the per-account
  login lockout.
- Anything not raised here (e.g. credential failure) is a VALUE returned to
  the caller, not an exception - only anomalous school behaviour raises.
"""

from typing import Final


class SelcrsError(Exception):
    """Base class for all adapter-raised errors."""


class SelcrsUnavailable(SelcrsError):
    """School unreachable/unrecognisable. Breaker input; never lockout input."""

    def __init__(self, detail: str) -> None:
        # Detail is a fixed, sanitized string - never a URL with credentials,
        # never a raw server dump (could echo submitted data at parse-boundary).
        super().__init__(detail)
        self.detail: Final = detail


class SelcrsSessionExpired(SelcrsError):
    """The school bounced a session-bound read back to its login page.

    Deterministic per-user state (the parked jar is dead), NOT school
    misbehaviour: deliberately NOT a SelcrsUnavailable subclass, so it never
    feeds the breaker and never counts toward lockout. Surfaced to the site
    user as 401 SELCRS_EXPIRED (frontend drives re-login).
    """

    def __init__(self, detail: str = "school session expired") -> None:
        super().__init__(detail)
        self.detail: Final = detail
