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
