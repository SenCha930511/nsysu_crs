import { describe, expect, it } from "vitest";

import type { CourseOut } from "./api";
import { totalCreditsAndHours } from "./totals";
import { UnknownPeriodCodeError } from "../config/timeslots";

let seq = 0;
function mkCourse(partial: Partial<CourseOut>): CourseOut {
  seq += 1;
  return {
    id: `total-${seq}`,
    year_sem: "1151",
    code: null,
    dept: null,
    grade: null,
    class_: null,
    name_zh: null,
    name_en: null,
    credit: null,
    compulsory: false,
    restrict: null,
    select_n: null,
    selected_n: null,
    remaining: null,
    teacher: null,
    room: null,
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

describe("totalCreditsAndHours", () => {
  it("sums credits and period hours over two courses including a 0-credit one", () => {
    const threeCredit = mkCourse({
      credit: 3,
      // Mon 567 = 3 hours, Fri 34 = 2 hours -> 5
      class_time: ["567", "", "", "", "34", "", ""],
    });
    const zeroCredit = mkCourse({
      credit: 0,
      // Wed C = 1 hour
      class_time: ["", "", "C", "", "", "", ""],
    });
    const totals = totalCreditsAndHours([threeCredit, zeroCredit]);
    expect(totals.totalCredits).toBe(3);
    expect(totals.totalHours).toBe(6);
    expect(totals.courseCount).toBe(2);
  });

  it("treats a missing credit (null) as 0", () => {
    const course = mkCourse({
      credit: null,
      class_time: ["A", "", "", "", "", "", ""],
    });
    const totals = totalCreditsAndHours([course]);
    expect(totals.totalCredits).toBe(0);
    expect(totals.totalHours).toBe(1);
  });

  it("returns zeros for an empty selection", () => {
    expect(totalCreditsAndHours([])).toEqual({
      totalCredits: 0,
      totalHours: 0,
      courseCount: 0,
    });
  });

  it("throws on unknown period codes instead of under-counting", () => {
    const corrupt = mkCourse({
      credit: 3,
      class_time: ["5Z", "", "", "", "", "", ""],
    });
    expect(() => totalCreditsAndHours([corrupt])).toThrow(
      UnknownPeriodCodeError,
    );
  });
});
