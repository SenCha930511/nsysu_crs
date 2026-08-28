/** Unit tests for the unified console staged ops (/ console grid merge). */
import { describe, expect, it } from "vitest";

import type { CourseOut, SelectionItem } from "./api";
import {
  mergeGridCourses,
  selectionGridKey,
  selectionShortCode,
  toWriteOps,
} from "./consoleOps";

function course(overrides: Partial<CourseOut>): CourseOut {
  return {
    id: "uuid-1",
    year_sem: "1151",
    code: "CSE515",
    dept: "資工碩",
    grade: null,
    class_: null,
    name_zh: "高等電腦網路",
    name_en: null,
    credit: 3,
    compulsory: true,
    restrict: 60,
    select_n: 50,
    selected_n: 40,
    remaining: 10,
    teacher: "林俊宏",
    room: "工EC 5012",
    class_time: ["", "", "234", "", "", "", ""],
    description: null,
    tags: null,
    english: false,
    change: null,
    change_desc: null,
    url: null,
    ingested_at: "2026-08-28T03:10:00+08:00",
    ...overrides,
  };
}

function sel(overrides: Partial<SelectionItem>): SelectionItem {
  return {
    code: "M3046243",
    course_no: "CSE515",
    state: "選上",
    dept: "資工碩",
    name: "高等電腦網路",
    credit: 3,
    compulsory_elective: "必",
    teacher: "林俊宏",
    room_text: "三2,3,4(工EC 5012)",
    points_priority: null,
    stage: "期",
    year_semest_note: "期",
    times: "三2,3,4",
    room: "工EC 5012",
    unknown: false,
    course_id: null,
    ...overrides,
  };
}

describe("selectionShortCode", () => {
  it("prefers course_no (課別代號) over the long 課程代碼", () => {
    expect(selectionShortCode(sel({}))).toBe("CSE515");
    expect(selectionShortCode(sel({ course_no: null }))).toBe("M3046243");
    expect(selectionShortCode(sel({ course_no: null, code: null }))).toBeNull();
  });
});

describe("selectionGridKey", () => {
  it("matches the merge identity used by the selections grid", () => {
    expect(selectionGridKey(sel({}))).toBe("M3046243");
    expect(selectionGridKey(sel({ course_id: "uuid-9" }))).toBe("uuid-9");
    expect(selectionGridKey(sel({ code: null }))).toBe("CSE515");
  });
});

describe("mergeGridCourses", () => {
  it("appends staged adds after the selections base", () => {
    const base = [course({ id: "CSE515" })];
    const adds = [course({ id: "GEAE2526", code: "GEAE2526" })];
    expect(mergeGridCourses(base, adds).map((c) => c.id)).toEqual(["CSE515", "GEAE2526"]);
  });
});

describe("toWriteOps", () => {
  it("sends adds with the catalog short code and drops with per-row typed confirm", () => {
    const { ops, unaddable } = toWriteOps(
      [
        { course: course({ id: "uuid-1", code: "GEAE2526" }), priority: 1 },
        { course: course({ id: "uuid-2", code: "MEME101B" }), priority: 2 },
      ],
      [sel({})],
    );
    expect(ops).toEqual([
      { action: "+", course_id: "GEAE2526", priority: 1 },
      { action: "+", course_id: "MEME101B", priority: 2 },
      { action: "-", course_id: "CSE515", drop_confirm_text: "CSE515" },
    ]);
    expect(unaddable).toEqual([]);
  });

  it("passes code-less adds to unaddable instead of inventing an ident", () => {
    const { ops, unaddable } = toWriteOps(
      [{ course: course({ id: "uuid-x", code: null, name_zh: "無碼課" }), priority: 1 }],
      [],
    );
    expect(ops).toEqual([]);
    expect(unaddable.map((c) => c.name_zh)).toEqual(["無碼課"]);
  });
});
