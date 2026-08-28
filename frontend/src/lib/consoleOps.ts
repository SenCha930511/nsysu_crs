/**
 * Unified-console staging math (HttpOnly-write flow): what turns the grid's
 * staged adds/drops into a preview batch, without ever inventing identities.
 * Identity law (2026-08-28, live-probed in qa/probe-crsno-desc.txt): the
 * school's write form accepts the 課別代號 (CSE515); the long 課程代碼 does
 * NOT resolve. Adds therefore send `catalog.code` (the CrsDat-derived short
 * code now backfilled on every catalog row); drops send the selection's own
 * `course_no ?? code`, with the typed-confirm field echoing the same value
 * (the school's per-drop 課號 confirmation).
 *
 * This module is pure + zero-IO so every identity decision stays testable.
 */
import type { CourseOut, SelectionItem, WriteOpIn } from "./api";

export interface StagedAdd {
  readonly course: CourseOut;
  readonly priority: number;
}

/** The write identity of a selection row (課別代號 preferred). */
export function selectionShortCode(item: SelectionItem): string | null {
  return item.course_no ?? item.code;
}

/** The grid identity of a selection row — mirrors selectionGrid mergeKey. */
export function selectionGridKey(item: SelectionItem): string {
  return item.course_id ?? item.code ?? item.course_no ?? `${item.name}|${item.teacher}`;
}

/** Grid courses = selections baseline followed by staged adds, order kept. */
export function mergeGridCourses(
  selectionsBaseline: readonly CourseOut[],
  stagedAdds: readonly CourseOut[],
): CourseOut[] {
  return [...selectionsBaseline, ...stagedAdds];
}

export interface WriteOpsResult {
  ops: WriteOpIn[];
  /** Adds with no catalog code — nothing inventable; surfaced, never sent. */
  unaddable: CourseOut[];
}

/**
 * Build the preview batch. Adds ride priority order (insert order, as
 * staged); drops follow with drop_confirm_text echoing the short code
 * (backend compares it verbatim against the resolved identity).
 */
export function toWriteOps(
  adds: readonly StagedAdd[],
  drops: readonly SelectionItem[],
): WriteOpsResult {
  const ops: WriteOpIn[] = [];
  const unaddable: CourseOut[] = [];
  for (const add of adds) {
    if (add.course.code === null) {
      unaddable.push(add.course);
      continue;
    }
    ops.push({
      action: "+",
      course_id: add.course.code,
      priority: add.priority,
    });
  }
  for (const item of drops) {
    const short = selectionShortCode(item);
    if (short === null) continue;
    ops.push({
      action: "-",
      course_id: short,
      drop_confirm_text: short,
    });
  }
  return { ops, unaddable };
}
