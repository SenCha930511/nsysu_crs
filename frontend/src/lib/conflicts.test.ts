import { describe, expect, it } from "vitest";

import type { CourseOut } from "./api";
import { conflictPairs, findClashes, isConflictDays } from "./conflicts";
import { UnknownPeriodCodeError } from "../config/timeslots";

/** Build a 7-slot Monday..Sunday class_time array from a day->string map. */
function classTime(spec: Record<number, string>): string[] {
  const days = ["", "", "", "", "", "", ""];
  for (const [index, codes] of Object.entries(spec)) {
    const day = Number(index);
    if (day < 0 || day > 6) {
      throw new Error(`bad day index in fixture: ${day}`);
    }
    days[day] = codes;
  }
  return days;
}

let seq = 0;
function mkCourse(partial: Partial<CourseOut>): CourseOut {
  seq += 1;
  return {
    id: `course-${seq}`,
    year_sem: "1151",
    code: null,
    dept: "資工系",
    grade: "1",
    class_: "甲班",
    name_zh: `測試課程${seq}`,
    name_en: null,
    credit: 3,
    compulsory: false,
    restrict: 60,
    select_n: 10,
    selected_n: 5,
    remaining: 55,
    teacher: "測試教師",
    room: "工EC5011",
    class_time: null,
    description: null,
    tags: null,
    english: false,
    change: null,
    change_desc: null,
    url: null,
    ingested_at: "2026-08-27T00:00:00Z",
    ...partial,
  };
}

describe("isConflictDays (per-day char-set intersection)", () => {
  it('conflicts when the same day shares a code: "56" vs "5B"', () => {
    const a = classTime({ 2: "56" });
    const b = classTime({ 2: "5B" });
    expect(isConflictDays(a, b)).toBe(true);
  });

  it('does not conflict on adjacent-but-different codes: "A" vs "1"', () => {
    const a = classTime({ 2: "A" });
    const b = classTime({ 2: "1" });
    expect(isConflictDays(a, b)).toBe(false);
  });

  it("does not conflict across different days even with identical codes", () => {
    const a = classTime({ 0: "567" });
    const b = classTime({ 1: "567" });
    expect(isConflictDays(a, b)).toBe(false);
  });

  it("handles empty slots and empty arrays", () => {
    expect(isConflictDays(classTime({}), classTime({}))).toBe(false);
    expect(isConflictDays([], classTime({ 0: "1" }))).toBe(false);
    expect(isConflictDays(classTime({ 4: "9C" }), classTime({}))).toBe(false);
  });

  it("matches multi-day schedules", () => {
    const a = classTime({ 0: "34", 4: "567" });
    const b = classTime({ 3: "1", 4: "789" });
    expect(isConflictDays(a, b)).toBe(true); // Friday 7 overlaps
    const c = classTime({ 3: "1", 4: "89" });
    expect(isConflictDays(a, c)).toBe(false);
  });

  it("throws on unknown period codes instead of guessing", () => {
    expect(() =>
      isConflictDays(classTime({ 0: "Z" }), classTime({ 0: "1" })),
    ).toThrow(UnknownPeriodCodeError);
    expect(() =>
      isConflictDays(classTime({ 2: "5Z" }), classTime({ 2: "5" })),
    ).toThrow(UnknownPeriodCodeError);
  });
});

describe("findClashes", () => {
  it("returns the clashing selected course with slot tags", () => {
    const selected = mkCourse({
      name_zh: "線性代數",
      class_time: classTime({ 2: "567" }),
    });
    const candidate = mkCourse({
      name_zh: "離散數學",
      class_time: classTime({ 2: "5B", 4: "34" }),
    });
    const clashes = findClashes(candidate, [selected]);
    expect(clashes).toHaveLength(1);
    expect(clashes[0]?.course.id).toBe(selected.id);
    expect(clashes[0]?.slotTags).toEqual(["三5"]);
  });

  it("ignores the candidate itself and conflict-free selections", () => {
    const course = mkCourse({ class_time: classTime({ 1: "12" }) });
    const free = mkCourse({ class_time: classTime({ 1: "34" }) });
    expect(findClashes(course, [course, free])).toEqual([]);
  });

  it("aggregates multiple slot tags across days", () => {
    const selected = mkCourse({ class_time: classTime({ 0: "12", 4: "56" }) });
    const candidate = mkCourse({
      class_time: classTime({ 0: "23", 4: "67" }),
    });
    const clashes = findClashes(candidate, [selected]);
    expect(clashes[0]?.slotTags).toEqual(["一2", "五6"]);
  });
});

describe("conflictPairs", () => {
  it("reports each clashing pair once", () => {
    const a = mkCourse({ class_time: classTime({ 0: "56" }) });
    const b = mkCourse({ class_time: classTime({ 0: "5B" }) });
    const c = mkCourse({ class_time: classTime({ 2: "12" }) });
    const pairs = conflictPairs([a, b, c]);
    expect(pairs).toHaveLength(1);
    expect(pairs[0]?.a.id).toBe(a.id);
    expect(pairs[0]?.b.id).toBe(b.id);
    expect(pairs[0]?.slotTags).toEqual(["一5"]);
  });
});
