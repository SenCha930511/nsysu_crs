"""End-of-job slt_result reconcile (plan todo 15 retry discipline).

Triggered ONLY when the batch POST was transport-retried and produced
``unknown-reconciled`` ops: with the session still alive the engine fetches
slt_result once and upgrades those outcomes to their real state. The
reconcile query's own failure is NEVER retried, and a dead/superseded
session is detected before the fetch — in both cases outcomes stay
``unknown-reconciled`` and the jobs API surfaces manual-resync-needed.
"""

import uuid
from typing import Final

from app.auth.redis_iface import AuthRedis
from app.auth.sessions import load_selcrs
from app.config import Settings
from app.selcrs.endpoints import get_slt_result
from app.selcrs.errors import SelcrsSessionExpired, SelcrsUnavailable
from app.selcrs.jar import deserialize_cookies
from app.selections.parse import SelectionItem, parse_slt_result
from app.write.canonical import CanonicalOp
from app.write.outcomes import (
    OUTCOME_FAILED,
    OUTCOME_SUCCESS,
    OUTCOME_UNKNOWN_RECONCILED,
)
from app.write.queue import QueueTicket

_SELECTED_STATES: Final = frozenset({"選上", "登記加選"})

#: update tuple shape: (audit_id, outcome, school_msg)
OutcomeUpdate = tuple[uuid.UUID, str, str | None]


def reconcile_updates(
    updates: list[OutcomeUpdate],
    ops: list[CanonicalOp],
    items: list[SelectionItem],
) -> list[OutcomeUpdate]:
    """Upgrade unknown-reconciled ops to their real slt_result state.

    Add: present with a selected state -> success; otherwise the dup-like
    claim could not be verified and the add genuinely failed. Drop mirrors
    it (absent / non-selected -> success).
    """
    states = {item.code: item.state for item in items if item.code is not None}
    reconciled: list[OutcomeUpdate] = []
    for (audit_id, outcome, msg), op in zip(updates, ops, strict=True):
        if outcome != OUTCOME_UNKNOWN_RECONCILED:
            reconciled.append((audit_id, outcome, msg))
            continue
        selected = states.get(op.code) in _SELECTED_STATES
        if op.action == "+":
            real = OUTCOME_SUCCESS if selected else OUTCOME_FAILED
            note = (
                "對帳確認:slt_result 載選上/登記加選"
                if selected
                else "對帳確認:slt_result 未選上,加選未成立"
            )
        else:
            real = OUTCOME_FAILED if selected else OUTCOME_SUCCESS
            note = (
                "對帳確認:slt_result 仍載選上,退選未成立"
                if selected
                else "對帳確認:slt_result 無選上紀錄,退選成立"
            )
        reconciled.append((audit_id, real, note))
    return reconciled


async def maybe_reconcile(
    redis: AuthRedis,
    settings: Settings,
    ticket: QueueTicket,
    ops: list[CanonicalOp],
    updates: list[OutcomeUpdate],
) -> list[OutcomeUpdate]:
    """Fetch slt_result once and reconcile (see module docstring)."""
    if not any(outcome == OUTCOME_UNKNOWN_RECONCILED for _, outcome, _ in updates):
        return updates
    jar_payload = await load_selcrs(
        redis, ticket.session_ref, sliding_ttl=settings.selcrs_session_ttl_sliding
    )
    if jar_payload is None:  # session dead/superseded: manual resync stays
        return updates
    try:
        html = await get_slt_result(deserialize_cookies(jar_payload))
        items = parse_slt_result(html)
    except (SelcrsUnavailable, SelcrsSessionExpired):
        return updates  # the reconcile query itself is never retried
    return reconcile_updates(updates, ops, items)
