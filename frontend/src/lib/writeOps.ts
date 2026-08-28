/**
 * /write (todo 16) pure logic: the ops composer reducer, verdict math, confirm
 * modal asserts, the staged-vs-actual reconcile diff, and ALL user-facing copy
 * tables for job statuses / op outcomes. Kept DOM-free so vitest (node env)
 * can lock behavior; WritePage is a thin renderer over these functions.
 *
 * Copy rules locked by tests:
 * - Business failures ("failed") must NEVER suggest auto-retry.
 * - session_superseded carries its own dedicated copy, never merged with
 *   generic failure text.
 */

import { applyPriorityEdit } from "./priority";
import type {
  CourseOut,
  JobOpOut,
  OpVerdictOut,
  SelectionItem,
  WriteOpIn,
} from "./api";
import { formatTimeTag } from "../config/timeslots";

// ---------- composer draft model ----------

export interface AddDraft {
  kind: "add";
  courseId: string;
  code: string | null;
  priority: number | null;
  course: CourseOut | null;
}

export interface DropDraft {
  kind: "drop";
  /** Stable row key (course code; codes are unique within selections). */
  key: string;
  /** Catalog UUID when the selection joined one, else null. */
  courseId: string | null;
  /** Long 課程代碼 (display only; never sent as identity). */
  code: string;
  /** Identity the user types and the backend compares: 課別代號 (course_no ?? code). */
  confirmCode: string;
  name: string;
  state: string;
  typed: string;
}

export type DraftOp = AddDraft | DropDraft;

export interface ComposerState {
  adds: AddDraft[];
  drops: DropDraft[];
  /** Machine code of the last rejected priority edit, or null. */
  priorityError: "priority_invalid" | "priority_range" | "priority_duplicate" | null;
  priorityErrorHolder: string | null;
}

export const INITIAL_COMPOSER: ComposerState = {
  adds: [],
  drops: [],
  priorityError: null,
  priorityErrorHolder: null,
};

/** Selection states that mean the school currently holds the course. */
const HELD_STATES: ReadonlySet<string> = new Set(["選上", "登記加選"]);

export function isHeldState(state: string): boolean {
  return HELD_STATES.has(state);
}

/**
 * Build the initial draft from ACTIVE-plan rows (add candidates, priority
 * editable) and synced selections (drop candidates, typed-code gated).
 * `priorTyped` lets a re-init (fresh boot data) keep already-typed codes.
 */
export function initComposer(
  planItems: readonly {
    courseId: string;
    priority: number | null;
    course: CourseOut | null;
  }[],
  selectionItems: readonly SelectionItem[],
  priorDrops: readonly DropDraft[] = [],
): ComposerState {
  const typedByKey = new Map(priorDrops.map((d) => [d.key, d.typed]));
  const adds: AddDraft[] = planItems.map((item) => ({
    kind: "add",
    courseId: item.courseId,
    code: item.course?.code ?? null,
    priority: item.priority,
    course: item.course,
  }));
  const drops: DropDraft[] = selectionItems
    .filter((item) => (item.code ?? item.course_no) !== null && isHeldState(item.state))
    .map((item) => {
      const key = (item.code ?? item.course_no) as string;
      const confirmCode = (item.course_no ?? item.code) as string;
      return {
        kind: "drop",
        key,
        courseId: item.course_id,
        code: item.code ?? confirmCode,
        confirmCode,
        name: item.name,
        state: item.state,
        typed: typedByKey.get(key) ?? "",
      };
    });
  return { adds, drops, priorityError: null, priorityErrorHolder: null };
}

export type ComposerAction =
  | { type: "setPriority"; courseId: string; raw: string }
  | { type: "clearPriorityError" }
  | { type: "setDropTyped"; key: string; typed: string }
  | { type: "removeAdd"; courseId: string }
  | { type: "removeDrop"; key: string }
  | {
      type: "reinit";
      planItems: readonly {
        courseId: string;
        priority: number | null;
        course: CourseOut | null;
      }[];
      selectionItems: readonly SelectionItem[];
    };

export function composerReducer(
  state: ComposerState,
  action: ComposerAction,
): ComposerState {
  switch (action.type) {
    case "setPriority": {
      const priorities: Record<string, number | null> = {};
      for (const add of state.adds) priorities[add.courseId] = add.priority;
      const orderedIds = state.adds.map((a) => a.courseId);
      const { priorities: next, result } = applyPriorityEdit(
        priorities,
        action.courseId,
        action.raw,
        orderedIds,
      );
      if (!result.ok) {
        return {
          ...state,
          priorityError: result.error,
          priorityErrorHolder: result.holderCourseId,
        };
      }
      return {
        ...state,
        adds: state.adds.map((a) =>
          a.courseId === action.courseId
            ? { ...a, priority: next[a.courseId] ?? null }
            : a,
        ),
        priorityError: null,
        priorityErrorHolder: null,
      };
    }
    case "clearPriorityError":
      return { ...state, priorityError: null, priorityErrorHolder: null };
    case "setDropTyped":
      return {
        ...state,
        drops: state.drops.map((d) =>
          d.key === action.key ? { ...d, typed: action.typed } : d,
        ),
      };
    case "removeAdd":
      return {
        ...state,
        adds: state.adds.filter((a) => a.courseId !== action.courseId),
      };
    case "removeDrop":
      return {
        ...state,
        drops: state.drops.filter((d) => d.key !== action.key),
      };
    case "reinit":
      return initComposer(action.planItems, action.selectionItems, state.drops);
  }
}

// ---------- composer -> preview ops ----------

/** A drop row may enter the batch only when the typed code matches exactly. */
export function dropIncludable(drop: Pick<DropDraft, "typed" | "confirmCode">): boolean {
  return drop.typed === drop.confirmCode;
}

/**
 * Ops for POST /api/write/preview: every add WITH a priority (priority-less
 * adds are surfaced as "未排志願" in the UI and stay out), plus drop rows
 * whose typed code matched. Drop `course_id` prefers the catalog UUID and
 * falls back to the 8-char code (the server resolves both).
 */
export function buildPreviewOps(state: ComposerState): WriteOpIn[] {
  const ops: WriteOpIn[] = [];
  for (const add of state.adds) {
    if (add.priority === null) continue;
    ops.push({ action: "+", course_id: add.courseId, priority: add.priority });
  }
  for (const drop of state.drops) {
    if (!dropIncludable(drop)) continue;
    ops.push({
      action: "-",
      course_id: drop.courseId ?? drop.confirmCode,
      drop_confirm_text: drop.typed,
    });
  }
  return ops;
}

/** Adds the composer cannot even send (no priority) — for UI hints. */
export function unprioritizedAdds(state: ComposerState): AddDraft[] {
  return state.adds.filter((a) => a.priority === null);
}

export function priorityErrorText(
  error: ComposerState["priorityError"],
): string | null {
  if (error === null) return null;
  return error === "priority_duplicate"
    ? "志願序不可重複"
    : "志願序須為 1–20 的整數";
}

// ---------- preview verdicts ----------

type VerdictRow = Pick<OpVerdictOut, "writable" | "verdict" | "detail" | "warnings">;

type WritableFlag = Pick<OpVerdictOut, "writable">;

export function blockedCount(preview: {
  ops: readonly WritableFlag[];
}): number {
  return preview.ops.filter((op) => !op.writable).length;
}

/** A batch is confirmable only with zero blocked rows AND a minted token. */
export function canConfirm(
  preview: {
    writable: boolean;
    confirm_token: string | null;
    ops: readonly WritableFlag[];
  } | null,
): boolean {
  if (preview === null) return false;
  return (
    preview.writable &&
    preview.confirm_token !== null &&
    preview.ops.every((op) => op.writable)
  );
}

export type VerdictTone = "blocked" | "warn" | "pass";

export function verdictTone(row: VerdictRow): VerdictTone {
  if (!row.writable) return "blocked";
  if (row.warnings.length > 0) return "warn";
  return "pass";
}

export function verdictLabel(row: VerdictRow): string {
  if (row.writable) return "通過";
  if (row.verdict === "衝堂" && row.detail !== null) {
    return `衝堂（與 ${row.detail}）`;
  }
  return row.verdict;
}

export function opWarningText(warning: string): string {
  switch (warning) {
    case "remaining_zero":
      return "名額快照顯示額滿（餘 0）；快照可能過期，學校判定為準";
    default:
      return warning;
  }
}

export function batchWarningText(
  warning: string,
  quotaAsOf: string | null,
): string {
  switch (warning) {
    case "quota_snapshot":
      return `名額為目錄快照${quotaAsOf !== null ? `（更新於 ${quotaAsOf}）` : ""}，僅供參考；實際以學校系統當下為準`;
    default:
      return warning;
  }
}

// ---------- confirm modal asserts ----------

export type ConfirmFormError = "password_required" | "drop_code_mismatch";

export interface ConfirmFormCheck {
  ok: boolean;
  error: ConfirmFormError | null;
  /** The first mismatching drop row (for the modal's inline error). */
  mismatchKey: string | null;
}

/**
 * Gate for the 確認送單 button: password re-entered (non-empty, never stored)
 * AND every drop op's typed code still matches its code (carried from the
 * composer and re-asserted here, immediately before submit).
 */
export function checkConfirmForm(
  password: string,
  drops: readonly Pick<DropDraft, "key" | "confirmCode" | "typed">[],
): ConfirmFormCheck {
  if (password.length === 0) {
    return { ok: false, error: "password_required", mismatchKey: null };
  }
  const mismatch = drops.find((d) => !dropIncludable(d));
  if (mismatch !== undefined) {
    return { ok: false, error: "drop_code_mismatch", mismatchKey: mismatch.key };
  }
  return { ok: true, error: null, mismatchKey: null };
}

export function confirmFormErrorText(error: ConfirmFormError): string {
  return error === "password_required"
    ? "請重新輸入選課密碼以確認身分"
    : "退選課號輸入不符，請回到上一步重新確認";
}

// ---------- job status / outcome copy ----------

export const TERMINAL_JOB_STATUSES: ReadonlySet<string> = new Set([
  "done",
  "failed",
  "cancelled",
  "session_superseded",
]);

export function isTerminalStatus(status: string): boolean {
  return TERMINAL_JOB_STATUSES.has(status);
}

export interface StatusCopy {
  label: string;
  /** Bootstrap contextual tone name (success/danger/warning/info/secondary). */
  tone: string;
}

export const JOB_STATUS_COPY: Record<string, StatusCopy> = {
  queued: { label: "排隊中", tone: "info" },
  running: { label: "送單中", tone: "info" },
  done: { label: "已完成", tone: "success" },
  failed: { label: "未完成", tone: "danger" },
  cancelled: { label: "已自動取消（排隊逾時）", tone: "warning" },
  session_superseded: { label: "已取消（工作階段被取代）", tone: "warning" },
};

export function jobStatusCopy(status: string): StatusCopy {
  return JOB_STATUS_COPY[status] ?? { label: status, tone: "secondary" };
}

export interface OutcomeCopy {
  label: string;
  tone: string;
  hint: string | null;
}

/**
 * The session_superseded outcome copy is FIXED TEXT shared by op rows, the
 * job banner, and tests — it must stay identical everywhere it appears.
 */
export const SUPERSEDED_COPY =
  "你已在別處重新登入，此批送單已取消，請重新預檢";

export const OUTCOME_COPY: Record<string, OutcomeCopy> = {
  success: { label: "成功", tone: "success", hint: null },
  failed: {
    label: "學校拒絕",
    tone: "danger",
    hint: "學校已拒絕此課，原因如上方學校訊息；此為最終結果。",
  },
  transport_failed: {
    label: "傳輸失敗",
    tone: "warning",
    hint: "與學校主機間傳輸異常（系統重送 2 次後已停止，未再自動送出）；請先用下方對帳確認實際狀態，再重新預檢。",
  },
  parse_failed: {
    label: "回應無法解析",
    tone: "warning",
    hint: "學校回應格式異常，無法判定結果；請以下方原文摘錄與對帳結果為準。",
  },
  階段逾時: {
    label: "階段逾時",
    tone: "warning",
    hint: "送單前登入工作階段已過期，本課未送出；請重新預檢並再次確認。",
  },
  "unknown-reconciled": {
    label: "結果不明",
    tone: "warning",
    hint: null, // resolved by unknownReconciledHint(reconcile)
  },
  session_superseded: {
    label: "已取消",
    tone: "warning",
    hint: SUPERSEDED_COPY,
  },
  pending: { label: "等待回應", tone: "secondary", hint: null },
};

export function outcomeCopy(outcome: string | null): OutcomeCopy {
  if (outcome === null) return OUTCOME_COPY.pending as OutcomeCopy;
  return (
    OUTCOME_COPY[outcome] ?? {
      label: outcome,
      tone: "secondary",
      hint: "學校回應無法歸類，以對帳結果為準。",
    }
  );
}

/** unknown-reconciled has two fixed variants keyed by the job reconcile flag. */
export function unknownReconciledHint(reconcile: string | null): string {
  return reconcile === "manual_resync_needed"
    ? "學校回應不明——請手動重新同步對帳"
    : "學校回應不明—已自動對帳";
}

/** Copy for the whole batch when the job itself ended cancelled-like. */
export function jobTerminalBanner(job: {
  status: string;
  message: string | null;
}): string | null {
  if (job.status === "session_superseded") return SUPERSEDED_COPY;
  return job.message;
}

// ---------- reconcile (staged intent vs latest school truth) ----------

export interface ReconcileRow {
  code: string;
  intent: "+" | "-";
  intentLabel: string;
  /** Latest school state for the code, or null when absent from 已選. */
  actualState: string | null;
  actualName: string | null;
  match: boolean;
}

export function buildReconcileRows(
  ops: readonly Pick<JobOpOut, "code" | "action" | "priority">[],
  items: readonly SelectionItem[],
): ReconcileRow[] {
  const byCode = new Map(items.map((item) => [item.code, item]));
  return ops.map((op) => {
    const held = byCode.get(op.code);
    const actuallyHeld = held !== undefined && isHeldState(held.state);
    const match = op.action === "+" ? actuallyHeld : !actuallyHeld;
    return {
      code: op.code,
      intent: op.action === "+" ? "+" : "-",
      intentLabel:
        op.action === "+"
          ? `加選${op.priority !== null ? `（志願 ${op.priority}）` : ""}`
          : "退選",
      actualState: held?.state ?? null,
      actualName: held?.name ?? null,
      match,
    };
  });
}

// ---------- row catalog info rendering helpers ----------

/** "三56、五123" style compact period string from a 7-slot class_time. */
export function formatPeriods(classTime: readonly string[] | null): string {
  if (classTime === null) return "";
  return classTime
    .map((raw, day) => (raw === "" ? "" : formatTimeTag(day, raw)))
    .filter((tag) => tag !== "")
    .join("、");
}
