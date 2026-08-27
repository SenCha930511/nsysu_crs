/**
 * Timeslot & weekday config for the weekly timetable.
 *
 * Adapted from NSYSU-OpenDev/NSYSUSelectorHelper (MIT License,
 * Copyright (c) Cellery Lin and whats2000):
 *   client-website/src/config.tsx (TIMESLOT, WEEKDAY)
 *   https://github.com/NSYSU-OpenDev/NSYSUSelectorHelper
 *
 * Our API's class_time is already the same shape as their classTime mapping:
 * 7 slots Monday..Sunday, each a string of single-char period codes
 * ("56" = periods 5 and 6). The parsing layer REJECTS unknown period codes
 * by throwing: a silently dropped code would hide a class from the grid and
 * corrupt conflict detection, so corrupt catalog data must fail loudly.
 */

export type PeriodCode =
  | "A" | "1" | "2" | "3" | "4" | "B" | "5" | "6"
  | "7" | "8" | "9" | "C" | "D" | "E" | "F";

export interface Timeslot {
  code: PeriodCode;
  start: string; // "07:00"
  end: string; // "07:50"
  startMin: number; // minutes since midnight (ordering/integrity checks)
  endMin: number;
}

/** The 15 period codes in chronological order with exact clock ranges. */
export const TIMESLOTS: readonly Timeslot[] = [
  { code: "A", start: "07:00", end: "07:50", startMin: 420, endMin: 470 },
  { code: "1", start: "08:10", end: "09:00", startMin: 490, endMin: 540 },
  { code: "2", start: "09:10", end: "10:00", startMin: 550, endMin: 600 },
  { code: "3", start: "10:10", end: "11:00", startMin: 610, endMin: 660 },
  { code: "4", start: "11:10", end: "12:00", startMin: 670, endMin: 720 },
  { code: "B", start: "12:10", end: "13:00", startMin: 730, endMin: 780 },
  { code: "5", start: "13:10", end: "14:00", startMin: 790, endMin: 840 },
  { code: "6", start: "14:10", end: "15:00", startMin: 850, endMin: 900 },
  { code: "7", start: "15:10", end: "16:00", startMin: 910, endMin: 960 },
  { code: "8", start: "16:10", end: "17:00", startMin: 970, endMin: 1020 },
  { code: "9", start: "17:10", end: "18:00", startMin: 1030, endMin: 1080 },
  { code: "C", start: "18:20", end: "19:10", startMin: 1100, endMin: 1150 },
  { code: "D", start: "19:15", end: "20:05", startMin: 1155, endMin: 1205 },
  { code: "E", start: "20:10", end: "21:00", startMin: 1210, endMin: 1260 },
  { code: "F", start: "21:05", end: "21:55", startMin: 1265, endMin: 1315 },
];

export const PERIOD_CODES: readonly PeriodCode[] = TIMESLOTS.map((t) => t.code);

const PERIOD_CODE_SET: ReadonlySet<string> = new Set(PERIOD_CODES);

export interface Weekday {
  /** Index into class_time arrays (0 = Monday .. 6 = Sunday). */
  index: number;
  /** Value of the /api/courses weekday filter (1 = Monday .. 7 = Sunday). */
  apiWeekday: number;
  label: string;
}

export const WEEKDAYS: readonly Weekday[] = [
  { index: 0, apiWeekday: 1, label: "一" },
  { index: 1, apiWeekday: 2, label: "二" },
  { index: 2, apiWeekday: 3, label: "三" },
  { index: 3, apiWeekday: 4, label: "四" },
  { index: 4, apiWeekday: 5, label: "五" },
  { index: 5, apiWeekday: 6, label: "六" },
  { index: 6, apiWeekday: 7, label: "日" },
];

export const WEEKDAY_LABELS: readonly string[] = WEEKDAYS.map((d) => d.label);

/** Raised when catalog data contains a period code we do not know. */
export class UnknownPeriodCodeError extends Error {
  readonly code: string;
  constructor(code: string) {
    super(`Unknown period code: ${JSON.stringify(code)}`);
    this.name = "UnknownPeriodCodeError";
    this.code = code;
  }
}

export function isPeriodCode(ch: string): ch is PeriodCode {
  return PERIOD_CODE_SET.has(ch);
}

/** Validate a single character as a period code; throws on unknown codes. */
export function assertPeriodCode(ch: string): PeriodCode {
  if (!isPeriodCode(ch)) {
    throw new UnknownPeriodCodeError(ch);
  }
  return ch;
}

const EMPTY_SET: ReadonlySet<PeriodCode> = new Set();

/**
 * Parse one day slot of a class_time array ("56") into a set of validated
 * period codes. Every character must be a known code; anything else throws
 * UnknownPeriodCodeError. Empty/blank slots parse to the empty set.
 */
export function parseDayTimeString(raw: string): ReadonlySet<PeriodCode> {
  if (raw.length === 0) {
    return EMPTY_SET;
  }
  const codes = new Set<PeriodCode>();
  for (const ch of raw) {
    codes.add(assertPeriodCode(ch));
  }
  return codes;
}

/** Format a day slot as a compact time tag, e.g. (2, "56") -> "三56". */
export function formatTimeTag(dayIndex: number, raw: string): string {
  const codes = parseDayTimeString(raw);
  const label = WEEKDAY_LABELS[dayIndex] ?? "?";
  return `${label}${[...codes].join("")}`;
}
