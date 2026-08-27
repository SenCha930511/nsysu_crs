"""Canonical idempotency spec for write batches (plan todos 14/15, pinned by
todo 15's ``canonical 規格`` and mirrored VERBATIM there - single module).

Rules, in order:

1. Sort ops by ``(action order -,+,N, then school code ascending)``.
2. Collapse consecutive identical ``(action, code)`` pairs (the sort makes
   duplicates adjacent; the first occurrence survives).
3. ``T`` (priority) is stripped for every non-``+`` action.
4. ``T`` for ``+`` is zero-padded to 2 digits.
5. Ops segments join as ``act:code:TT|...``; the canonical string is
   ``student_no|<segments>``; ``payload_hash`` = its sha256 hex.

confirm_token (todo 14): ``base64url(sha256("student_no|canonical_ops|APP_SECRET"))``
where ``canonical_ops`` is the segments string from step 5 - i.e. the
canonical string with the secret appended. Padding is stripped (the token is
a Redis key component and a JSON value; stripped urlsafe base64 is the
canonical form on both sides of todo 15's confirm boundary).

Plan-pinned test vector (test_write_canonical.py):
``+A:12345678:01,-B:87654321:`` and ``-B:87654321:,+A:12345678:1``
canonicalize to the same string and therefore hash identically.
"""

import base64
import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

#: Action ordering key: -, +, N (plan todo 15).
ACTION_ORDER: Final = {"-": 0, "+": 1, "N": 2}


@dataclass(frozen=True, slots=True)
class CanonicalOp:
    """One op in canonical form: school code + action + (optional) priority.

    ``N`` exists for canonical-spec completeness (a form row's rest state);
    preview batches only ever carry ``+``/``-``.
    """

    action: str
    code: str
    priority: int | None = None

    def __post_init__(self) -> None:
        if self.action not in ACTION_ORDER:
            raise ValueError(f"unknown action: {self.action!r}")
        if self.action == "+" and self.priority is None:
            raise ValueError("add ops carry a priority")
        if self.action != "+" and self.priority is not None:
            raise ValueError("non-add ops never carry a priority")


def canonical_ops(ops: Iterable[CanonicalOp]) -> tuple[CanonicalOp, ...]:
    """Sort + collapse per steps 1-2 (deterministic, input-order stable)."""
    ordered = sorted(ops, key=lambda op: (ACTION_ORDER[op.action], op.code))
    collapsed: list[CanonicalOp] = []
    for op in ordered:
        if collapsed and collapsed[-1].action == op.action and collapsed[-1].code == op.code:
            continue
        collapsed.append(op)
    return tuple(collapsed)


def canonical_segments(ops: Iterable[CanonicalOp]) -> str:
    """The ``act:code:TT|...`` ops portion (steps 3-5, canonical input)."""
    segments = []
    for op in ops:
        tt = f"{op.priority:02d}" if op.action == "+" and op.priority is not None else ""
        segments.append(f"{op.action}:{op.code}:{tt}")
    return "|".join(segments)


def parse_canonical_segments(segments: str) -> tuple[CanonicalOp, ...]:
    """Inverse of ``canonical_segments`` (todo 15 confirm: the stored record
    carries only the segments string; the submit side re-derives the ops and,
    with the student number, the payload_hash preimage). Raises ValueError on
    any malformed segment - a corrupt record must not enqueue."""
    ops: list[CanonicalOp] = []
    for segment in segments.split("|"):
        action, separator, rest = segment.partition(":")
        if not separator or action not in ACTION_ORDER:
            raise ValueError(f"malformed canonical segment: {segment!r}")
        code, separator, tt = rest.partition(":")
        if not separator or not code:
            raise ValueError(f"malformed canonical segment: {segment!r}")
        if action == "+":
            if not tt.isdigit():
                raise ValueError(f"add segment without TT: {segment!r}")
            ops.append(CanonicalOp(action=action, code=code, priority=int(tt)))
        else:
            if tt:
                raise ValueError(f"non-add segment carrying TT: {segment!r}")
            ops.append(CanonicalOp(action=action, code=code))
    return tuple(ops)


def canonical_string(student_no: str, ops: Iterable[CanonicalOp]) -> str:
    """``student_no|act:code:TT|...`` - the payload-hash preimage. Total:
    sorting + collapse happen HERE too, so any op order yields the same
    string (callers can never pass an uncanonicalized batch by mistake)."""
    segments = canonical_segments(canonical_ops(ops))
    return f"{student_no}|{segments}" if segments else f"{student_no}|"


def payload_hash(student_no: str, ops: Iterable[CanonicalOp]) -> str:
    """sha256 hex of the canonical string (write_jobs.payload_hash)."""
    return hashlib.sha256(canonical_string(student_no, ops).encode("utf-8")).hexdigest()


def _b64url_nopad(digest: bytes) -> str:
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def confirm_token(student_no: str, ops: Iterable[CanonicalOp], *, secret: str) -> str:
    """``base64url(sha256(student_no + '|' + canonical_ops + '|' + secret))``.

    Deterministic per (student, canonical ops): a re-preview of the same
    batch re-mints the same token, which the confirm side (todo 15) consumes
    single-use via GETDEL - replay lands on the same idempotency key.
    """
    ops = tuple(ops)
    preimage = f"{student_no}|{canonical_segments(ops)}|{secret}"
    return _b64url_nopad(hashlib.sha256(preimage.encode("utf-8")).digest())
