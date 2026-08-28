/** Unit tests for selection -> timetable grid conversion (/selected feature). */
import { describe, expect, it } from "vitest";

import type { SelectionItem } from "./api";
import { buildSelectionGridCourses, parseSchoolTimes } from "./selectionGrid";

describe("parseSchoolTimes", () => {
  it("parses comma-separated digit codes, sorting chronologically per day", () => {
    expect(parseSchoolTimes("一2,3,4")).toEqual(["234", "", "", "", "", "", ""]);
    expect(parseSchoolTimes("四8,6,7")).toEqual(["", "", "", "678", "", "", ""]);
    expect(parseSchoolTimes("三2,3,4")).toEqual(["", "", "234", "", "", "", ""]);
  });

  it("handles single codes, full-width commas, and letter periods", () => {
    expect(parseSchoolTimes("五6")).toEqual(["", "", "", "", "6", "", ""]);
    expect(parseSchoolTimes("日C，D")).toEqual(["", "", "", "", "", "", "CD"]);
    expect(parseSchoolTimes("一A,5,6")).toEqual(["A56", "", "", "", "", "", ""]);
  });

  it("returns null for unparseable shapes (never a partial grid)", () => {
    expect(parseSchoolTimes("")).toBeNull();
    expect(parseSchoolTimes("六")).toBeNull();
    expect(parseSchoolTimes("星期六")).toBeNull();
    expect(parseSchoolTimes("X2,3")).toBeNull();
    expect(parseSchoolTimes("一12,34")).toBeNull();
  });
});

function sel(overrides: Partial<SelectionItem>): SelectionItem {
  return {
    code: null,
    course_no: null,
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

describe("buildSelectionGridCourses", () => {
  it("places only 選上 rows and synthesizes grid blocks", () => {
    const { courses, unplaced } = buildSelectionGridCourses([
      sel({ course_no: "CSE515", times: "三2,3,4", room: "工EC 5012" }),
      sel({ course_no: "CSE999", state: "登記加選" }),
      sel({ course_no: "CSE888", state: "失敗" }),
    ]);
    expect(courses).toHaveLength(1);
    expect(courses[0]?.id).toBe("CSE515");
    expect(courses[0]?.class_time).toEqual(["", "", "234", "", "", "", ""]);
    expect(courses[0]?.name_zh).toBe("高等電腦網路");
    expect(courses[0]?.room).toBe("工EC 5012");
    expect(unplaced).toHaveLength(0);
  });

  it("merges the same course when it meets on multiple days (separate rows)", () => {
    const { courses } = buildSelectionGridCourses([
      sel({ course_no: "CSE777", times: "一2,3", room: "R1" }),
      sel({ course_no: "CSE777", times: "五8,9", room: "R2" }),
    ]);
    expect(courses).toHaveLength(1);
    expect(courses[0]?.class_time).toEqual(["23", "", "", "", "89", "", ""]);
  });

  it("routes rows with missing/unparseable times to unplaced (no silent drop)", () => {
    const { courses, unplaced } = buildSelectionGridCourses([
      sel({ course_no: "CSE100", times: null, room: null }),
      sel({ course_no: "CSE101", times: "上課時間未定" }),
    ]);
    expect(courses).toHaveLength(0);
    expect(unplaced.map((u) => u.course_no)).toEqual(["CSE100", "CSE101"]);
  });

  it("prefers course_id, then code, then course_no, then name+teacher as the merge key", () => {
    const { courses } = buildSelectionGridCourses([
      sel({ course_id: "uuid-1", code: "AB123456", course_no: "CSE1", times: "一1" }),
      sel({ course_id: "uuid-1", code: "AB123456", course_no: "CSE1", times: "三3" }),
    ]);
    expect(courses).toHaveLength(1);
    expect(courses[0]?.id).toBe("uuid-1");
    expect(courses[0]?.class_time).toEqual(["1", "", "3", "", "", "", ""]);
  });
});
