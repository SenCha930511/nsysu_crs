/**
 * Pure date logic for the 選課日程 widget (GET /api/schedule payload).
 *
 * All derivations ride an explicit ``now`` so vitest pins every boundary
 * with zero timers; the component only re-renders the countdown text off a
 * slow interval and refetches rarely - the school page moves once a term.
 */

import type { ScheduleEventDto } from "./api";

export type RowState = "done" | "active" | "upcoming";

export interface ScheduleRow {
  event: ScheduleEventDto;
  state: RowState;
  start: Date;
  end: Date | null;
}

export interface NextPoint {
  event: ScheduleEventDto;
  at: Date;
  /** Window not yet begun vs a standalone 公佈 instant. */
  kind: "start" | "instant";
}

export interface DerivedSchedule {
  /** The window the user is inside right now, if any. */
  active: ScheduleRow | null;
  /** Nearest future point (a window's start or an upcoming 公佈). */
  next: NextPoint | null;
  rows: ScheduleRow[];
}

export function deriveScheduleState(
  events: ScheduleEventDto[],
  now: Date,
): DerivedSchedule {
  const rows: ScheduleRow[] = [];
  for (const event of events) {
    const start = new Date(event.start);
    const end = event.end !== null ? new Date(event.end) : null;
    if (Number.isNaN(start.getTime()) || (end !== null && Number.isNaN(end.getTime()))) {
      continue; // a malformed cached blob must not break the widget
    }
    let state: RowState;
    if (event.kind === "window" && end !== null) {
      state = now < start ? "upcoming" : now < end ? "active" : "done";
    } else {
      state = now < start ? "upcoming" : "done";
    }
    rows.push({ event, state, start, end });
  }
  const active = rows.find((row) => row.state === "active") ?? null;
  let next: NextPoint | null = null;
  for (const row of rows) {
    // The active window's own countdown rides ``active.end`` at the call
    // site; ``next`` looks strictly beyond it (upcoming rows only).
    if (row.state !== "upcoming") continue;
    if (next === null || row.start < next.at) {
      next = {
        event: row.event,
        at: row.start,
        kind: row.event.kind === "instant" ? "instant" : "start",
      };
    }
  }
  return { active, next, rows };
}

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** Human countdown for a future target: clamps at zero, "<1m" floor. */
export function formatCountdown(targetMs: number, lang: "zh" | "en"): string {
  const ms = Math.max(targetMs, 0);
  const days = Math.floor(ms / DAY);
  const hours = Math.floor((ms % DAY) / HOUR);
  const minutes = Math.floor((ms % HOUR) / MINUTE);
  if (days > 0) {
    return lang === "zh" ? `${days} 天 ${hours} 小時` : `${days}d ${hours}h`;
  }
  if (hours > 0) {
    return lang === "zh" ? `${hours} 小時 ${minutes} 分鐘` : `${hours}h ${minutes}m`;
  }
  if (minutes >= 1) {
    return lang === "zh" ? `${minutes} 分鐘` : `${minutes}m`;
  }
  return lang === "zh" ? "不到 1 分鐘" : "<1m";
}

/** English names for the school's stable event keys (labels stay verbatim
 * in zh; unknown keys fall back to the school's own wording). */
export const EVENT_LABELS_EN: Readonly<Record<string, string>> = {
  first_round_1: "First-round 1",
  first_round_1_result: "First-round 1 results",
  first_round_2: "First-round 2",
  first_round_2_result: "First-round 2 results",
  add_drop_1: "Add/drop 1",
  add_drop_1_result: "Add/drop 1 results",
  add_drop_2: "Add/drop 2",
  add_drop_2_result: "Add/drop 2 results",
  exception: "Exception handling",
  overload_print: "Overload form print",
  withdrawal: "Course withdrawal",
  confirmation: "Selection confirmation",
};

export function eventLabel(event: ScheduleEventDto, lang: "zh" | "en"): string {
  return lang === "zh" ? event.label : (EVENT_LABELS_EN[event.key] ?? event.label);
}
