"""Pure per-op preview check evaluator (plan todo 14 checks 3-7 + quota).

Inputs are fully resolved boundary values (CourseInfo per op, selections as
clash targets + code set), so this module has zero IO and is the QA surface
for the plan's "檢查逐項可觸發" - every verdict is provable offline.

Check order per op (first failure wins; the later checks need the earlier
inputs - a code-less row cannot meaningfully be conflict-checked):

3. ``無課號``      — catalog row missing or its code is NULL.
7. ``同批加退混雜`` — the same code appears with both ``+`` and ``-`` here.
6. ``不在已選``     — ``-`` op whose code is not in the latest synced selections.
4. ``衝堂``        — ``+`` op clashing current selections or an earlier
                     STAGED add of this batch (todo-10 rule), detail = the
                     clashing code.

``衝堂`` staged-set semantics (check 4, "已選+目標"): only adds that pass
their own earlier checks seed the staged set - a blocked op is not being
submitted, so nothing can clash with it. Iteration is request order, so the
reported earlier-later pair is deterministic.

Warnings never block (check 5): quota numbers are the ingest SNAPSHOT; a
``remaining_zero`` warning rides the op, and the batch response carries the
snapshot notice (the school's own verdict at submit is authoritative).
"""

from dataclasses import dataclass
from typing import Final

from app.write.catalog import CourseInfo
from app.write.timetable import is_conflict_days

VERDICT_OK: Final = "ok"
VERDICT_NO_CODE: Final = "無課號"
VERDICT_MIXED: Final = "同批加退混雜"
VERDICT_NOT_SELECTED: Final = "不在已選"
VERDICT_CONFLICT: Final = "衝堂"

WARN_REMAINING_ZERO: Final = "remaining_zero"


@dataclass(frozen=True, slots=True)
class ResolvedOp:
    """One request op after catalog resolution (index = request position)."""

    index: int
    action: str
    ident: str
    priority: int | None
    course: CourseInfo


@dataclass(frozen=True, slots=True)
class ClashTarget:
    """A current selection as a timetable (label = code when the school gave
    one, else the course_no|name identity)."""

    label: str
    days: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OpVerdict:
    """One op's check outcome (writable=True only on verdict "ok")."""

    index: int
    action: str
    ident: str
    code: str | None
    writable: bool
    verdict: str
    detail: str | None = None
    warnings: tuple[str, ...] = ()
    course: CourseInfo | None = None


def evaluate_ops(
    ops: list[ResolvedOp],
    *,
    selected_codes: frozenset[str],
    selection_targets: list[ClashTarget],
) -> list[OpVerdict]:
    """Run checks 3/7/6/4 in precedence order over the whole batch."""
    mixed_codes = {
        code
        for code in {op.course.code for op in ops if op.course.code is not None}
        if any(op.action == "+" and op.course.code == code for op in ops)
        and any(op.action == "-" and op.course.code == code for op in ops)
    }
    staged: list[ResolvedOp] = []  # accepted '+' ops so far (request order)
    verdicts: list[OpVerdict] = []
    for op in ops:
        code = op.course.code
        warnings: list[str] = []
        clash_with: str | None = None
        if code is None:
            verdicts.append(
                OpVerdict(
                    op.index, op.action, op.ident, None, False, VERDICT_NO_CODE,
                    course=op.course,
                )
            )
            continue
        verdict = VERDICT_OK
        if code in mixed_codes:
            verdict, clash_with = VERDICT_MIXED, None
        elif op.action == "-" and code not in selected_codes:
            verdict = VERDICT_NOT_SELECTED
        elif op.action == "+":
            if op.course.remaining == 0:
                warnings.append(WARN_REMAINING_ZERO)
            for target in selection_targets:
                if is_conflict_days(op.course.class_time, target.days):
                    verdict, clash_with = VERDICT_CONFLICT, target.label
                    break
            if verdict == VERDICT_OK:
                for earlier in staged:
                    if is_conflict_days(op.course.class_time, earlier.course.class_time):
                        verdict, clash_with = VERDICT_CONFLICT, earlier.course.code
                        break
        ok = verdict == VERDICT_OK
        if ok and op.action == "+":
            staged.append(op)
        verdicts.append(
            OpVerdict(
                op.index,
                op.action,
                op.ident,
                code,
                ok,
                verdict,
                detail=clash_with,
                warnings=tuple(warnings),
                course=op.course,
            )
        )
    return verdicts
