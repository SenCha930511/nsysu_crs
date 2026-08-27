"""Per-op outcome vocabulary of the write engine (plan todo 15).

The outcome of every school-posting attempt is recorded verbatim on
``write_audit.outcome`` and surfaced through ``GET /api/write/jobs/{id}``.
Terminal-ness is semantic: business failures are terminal immediately (plan:
"業務失敗=終態"), transport failures are terminal only after the engine's
<=2-retry discipline is exhausted, and ``unknown-reconciled`` is the honest
holding state for a transport-retried op whose duplicate-like business
failure could not be verified against slt_result (manual resync is the
fallback there, never a guessed outcome).
"""

from typing import Final

#: The school accepted the op.
OUTCOME_SUCCESS: Final = "success"
#: The school rejected the op with a business message (額滿/衝堂/違規...).
OUTCOME_FAILED: Final = "failed"
#: Transport errors past the engine retry budget (<=2 retries, adapter
#: backoff); the op's school-side state is NOT asserted.
OUTCOME_TRANSPORT_FAILED: Final = "transport_failed"
#: The school response could not be parsed per-op; the raw excerpt is stored
#: in school_msg and the outcome is never guessed (plan: "parse failure ->
#: outcome 'parse_failed' + raw excerpt stored, never guessed").
OUTCOME_PARSE_FAILED: Final = "parse_failed"
#: The selcrs session was dead when the job was dequeued (plan literal
#: 「階段逾時」): every op of the job lands here, terminal, no retry.
OUTCOME_STAGE_EXPIRED: Final = "階段逾時"
#: A transport-retried op whose school answer was duplicate-like. The first
#: POST may have landed: outcome stays here unless the end-of-job slt_result
#: reconcile upgrades it to its real state (plan todo 15 Retry discipline).
OUTCOME_UNKNOWN_RECONCILED: Final = "unknown-reconciled"
#: The job was superseded/cancelled (new login or dwell guard) while this
#: audit row was still pending; no school posting happened for the op.
OUTCOME_SUPERSEDED: Final = "session_superseded"
#: Audit-row placeholder between the fail-closed pre-insert (before ANY
#: school contact) and the outcome write-back after the batch POST. A row
#: left at pending means the engine crashed mid-run; dwell/sweep tooling
#: treats pending rows as forensics, never as outcomes to display.
OUTCOME_PENDING: Final = "pending"

#: Outcomes a UI may render as final per-op states.
DISPLAY_OUTCOMES: Final = (
    OUTCOME_SUCCESS,
    OUTCOME_FAILED,
    OUTCOME_TRANSPORT_FAILED,
    OUTCOME_PARSE_FAILED,
    OUTCOME_STAGE_EXPIRED,
    OUTCOME_UNKNOWN_RECONCILED,
    OUTCOME_SUPERSEDED,
)
