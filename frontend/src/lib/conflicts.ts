/**
 * Time-conflict detection over class_time strings.
 *
 * Adapted from NSYSU-OpenDev/NSYSUSelectorHelper (MIT License,
 * Copyright (c) Cellery Lin and whats2000):
 *   client-website/src/components/SelectorSetting.tsx (isConflict,
 *   detectTimeConflict)
 *   https://github.com/NSYSU-OpenDev/NSYSUSelectorHelper
 *
 * Same rule as upstream: two courses clash iff on any weekday their period
 * strings share at least one code (per-day char-set intersection). "56" vs
 * "5B" on the same day conflicts (period 5); "A" vs "1" on the same day does
 * not; identical periods on different days never conflict. Unknown codes are
 * rejected by the timeslot parsing layer (throws, never silently ignored).
 */

import { parseDayTimeString, WEEKDAY_LABELS } from "../config/timeslots";
import type { PeriodCode } from "../config/timeslots";
import type { CourseOut } from "./api";

function slot(classTime: readonly string[], dayIndex: number): string {
  return classTime[dayIndex] ?? "";
}

/**
 * Per-day char-set intersection over two 7-slot class_time arrays.
 * Day strings are validated as they are read: an unknown period code throws
 * UnknownPeriodCodeError. Slots beyond index 6 are never read (a malformed
 * longer array still compares only Monday..Sunday).
 */
export function isConflictDays(
  a: readonly string[],
  b: readonly string[],
): boolean {
  for (let day = 0; day < 7; day++) {
    const codesA = parseDayTimeString(slot(a, day));
    if (codesA.size === 0) continue;
    const codesB = parseDayTimeString(slot(b, day));
    for (const code of codesA) {
      if (codesB.has(code)) {
        return true;
      }
    }
  }
  return false;
}

/** Two-course convenience wrapper over isConflictDays. */
export function isConflict(a: CourseOut, b: CourseOut): boolean {
  return isConflictDays(a.class_time ?? [], b.class_time ?? []);
}

export interface Clash {
  /** The already-selected course this course clashes with. */
  course: CourseOut;
  /** Human-readable overlapping slot tags, e.g. "三5" (for tooltips). */
  slotTags: string[];
}

function overlapTags(
  candidate: readonly string[],
  selected: readonly string[],
): string[] {
  const tags: string[] = [];
  for (let day = 0; day < 7; day++) {
    const codesA = parseDayTimeString(slot(candidate, day));
    if (codesA.size === 0) continue;
    const codesB = parseDayTimeString(slot(selected, day));
    const shared: PeriodCode[] = [...codesA].filter((c) => codesB.has(c));
    if (shared.length > 0) {
      tags.push(`${WEEKDAY_LABELS[day] ?? "?"}${shared.join("")}`);
    }
  }
  return tags;
}

/**
 * All clashes between a candidate course and the current selection, in
 * selection order. An empty array means the candidate is conflict-free.
 */
export function findClashes(
  candidate: CourseOut,
  selected: readonly CourseOut[],
): Clash[] {
  const candidateTime = candidate.class_time ?? [];
  const clashes: Clash[] = [];
  for (const other of selected) {
    if (other.id === candidate.id) continue;
    const tags = overlapTags(candidateTime, other.class_time ?? []);
    if (tags.length > 0) {
      clashes.push({ course: other, slotTags: tags });
    }
  }
  return clashes;
}

export interface ConflictPair {
  a: CourseOut;
  b: CourseOut;
  slotTags: string[];
}

/** All clashing pairs inside the selection (drives the totals warning). */
export function conflictPairs(
  selected: readonly CourseOut[],
): ConflictPair[] {
  const pairs: ConflictPair[] = [];
  for (let i = 0; i < selected.length; i++) {
    const a = selected[i];
    if (a === undefined) continue;
    for (let j = i + 1; j < selected.length; j++) {
      const b = selected[j];
      if (b === undefined) continue;
      const tags = overlapTags(a.class_time ?? [], b.class_time ?? []);
      if (tags.length > 0) {
        pairs.push({ a, b, slotTags: tags });
      }
    }
  }
  return pairs;
}
