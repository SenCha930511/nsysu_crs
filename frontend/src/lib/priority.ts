/**
 * 志願序 (wish priority) rules, pure and shared by the dnd list + manual edits:
 *
 * - Priority domain: int 1..20, or null (unprioritized). At most ONE course
 *   may hold any given priority - manual edits violating that are rejected,
 *   drag reorders can never produce it by construction.
 * - Display order: priority ascending, nulls last, ties by the incoming
 *   (selection/add) order - identical to the server's list ordering, so a
 *   PUT (sent in display order) re-reads in the same order.
 * - Drag reorder semantics: drop positions 1..min(N,20) become priority 1..N,
 *   anything past 20 falls back to unprioritized (never a silent >20).
 */

export const PRIORITY_MAX = 20;

export type PriorityMap = Record<string, number | null>;

/**
 * Stable ordering: prioritized first (asc), then unprioritized in input
 * order. Ties should not exist (one course per priority); if they do, the
 * first in input order wins - dedupe is the caller's contract.
 */
export function orderIdsByPriority(
  ids: readonly string[],
  priorities: PriorityMap,
): string[] {
  return ids
    .map((id, index) => ({ id, index, priority: priorities[id] ?? null }))
    .sort((a, b) => {
      if (a.priority === null && b.priority === null) return a.index - b.index;
      if (a.priority === null) return 1;
      if (b.priority === null) return -1;
      return a.priority === b.priority
        ? a.index - b.index
        : a.priority - b.priority;
    })
    .map((entry) => entry.id);
}

/**
 * After a drag reorder, assign display positions as priorities: position i
 * (0-based) -> priority i+1 while i < PRIORITY_MAX, else null.
 */
export function assignSequentialPriority(orderedIds: readonly string[]): PriorityMap {
  const next: PriorityMap = {};
  orderedIds.forEach((id, index) => {
    next[id] = index < PRIORITY_MAX ? index + 1 : null;
  });
  return next;
}

export interface PriorityEditOk {
  ok: true;
  priority: number | null;
}

export interface PriorityEditRejected {
  ok: false;
  /** Stable machine code for tests + UI copy mapping. */
  error: "priority_invalid" | "priority_range" | "priority_duplicate";
  /** For duplicates: the course currently holding the number. */
  holderCourseId: string | null;
}

export type PriorityEditResult = PriorityEditOk | PriorityEditRejected;

/**Manual edit of one row: "" -> clear (null); 1..20 unique; else rejected. */
export function applyPriorityEdit(
  priorities: PriorityMap,
  courseId: string,
  rawValue: string,
  orderedIds: readonly string[],
): { priorities: PriorityMap; result: PriorityEditResult } {
  const trimmed = rawValue.trim();
  if (trimmed === "") {
    return {
      priorities: { ...priorities, [courseId]: null },
      result: { ok: true, priority: null },
    };
  }
  const numeric = Number(trimmed);
  if (!Number.isInteger(numeric) || !/^\d+$/.test(trimmed)) {
    return {
      priorities,
      result: { ok: false, error: "priority_invalid", holderCourseId: null },
    };
  }
  if (numeric < 1 || numeric > PRIORITY_MAX) {
    return {
      priorities,
      result: { ok: false, error: "priority_range", holderCourseId: null },
    };
  }
  const holder = orderedIds.find(
    (id) => id !== courseId && (priorities[id] ?? null) === numeric,
  );
  if (holder !== undefined) {
    return {
      priorities,
      result: { ok: false, error: "priority_duplicate", holderCourseId: holder },
    };
  }
  const next: PriorityMap = { ...priorities, [courseId]: numeric };
  return { priorities: next, result: { ok: true, priority: numeric } };
}
