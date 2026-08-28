/**
 * /selected weekly-grid conversion: school slt_result rows only carry the
 * fused 教室 token ("三2,3,4(工EC 5012)" -> times="三2,3,4") — the catalog
 * class_time join matches nothing today because courses.code is NULL
 * everywhere (verified-facts; no 課程代碼 in dplycourse). So the grid parses
 * the school times string here instead: strictly (single-char period codes
 * only, full-shape regex — partial cells would silently hide class hours).
 * Rows that cannot be parsed go to `unplaced` and stay in the card list —
 * never dropped.
 */
import type { CourseOut, SelectionItem } from "./api";
import { PERIOD_CODES, WEEKDAY_LABELS } from "../config/timeslots";

const PERIOD_ORDER: ReadonlyMap<string, number> = new Map(
  PERIOD_CODES.map((code, index) => [code, index]),
);

/**
 * Parse one fused school times token ("一2,3,4" / "四8,6,7") into the
 * class_time 7-slot array used by the weekly grid. Returns null when the
 * token is not exactly "weekday + comma-separated single period codes".
 */
export function parseSchoolTimes(times: string): string[] | null {
  const dayIndex = WEEKDAY_LABELS.indexOf(times.slice(0, 1));
  if (dayIndex < 0) return null;
  const tokens = times
    .slice(1)
    .split(/[,，]/)
    .map((token) => token.trim());
  if (tokens.length === 0 || tokens.some((token) => token.length !== 1)) return null;
  const seen = new Set<string>();
  for (const token of tokens) {
    if (!PERIOD_ORDER.has(token)) return null;
    seen.add(token);
  }
  const slots = Array.from({ length: 7 }, () => "");
  slots[dayIndex] = PERIOD_CODES.filter((code) => seen.has(code)).join("");
  return slots;
}

function unionDaySlots(left: string, right: string): string {
  const both = new Set([...left, ...right]);
  return PERIOD_CODES.filter((code) => both.has(code)).join("");
}

function mergeKey(item: SelectionItem): string {
  return item.course_id ?? item.code ?? item.course_no ?? `${item.name}|${item.teacher}`;
}

function toCourseOut(item: SelectionItem, classTime: string[], id: string): CourseOut {
  return {
    id,
    year_sem: "",
    code: item.code,
    dept: item.dept === "" ? null : item.dept,
    grade: null,
    class_: null,
    name_zh: item.name,
    name_en: null,
    credit: item.credit,
    compulsory: item.compulsory_elective === "必",
    restrict: null,
    select_n: null,
    selected_n: null,
    remaining: null,
    teacher: item.teacher === "" ? null : item.teacher,
    room: item.room,
    class_time: classTime,
    description: null,
    tags: null,
    english: false,
    change: null,
    change_desc: null,
    url: null,
    ingested_at: "",
  };
}

export interface SelectionGridResult {
  /** rows ready for the ScheduleTable grid (選上 only, times parsed). */
  courses: CourseOut[];
  /** 選上 rows whose times could not be parsed — shown in the cards below. */
  unplaced: SelectionItem[];
}

/**
 * Build grid-ready courses from a selections snapshot. Only state="選上"
 * occupies physical slots (登記加選/失敗 stay off the weekly grid). Rows of
 * the same course (multi-day meetings split by the school) merge into one
 * course block with unioned day slots.
 */
export function buildSelectionGridCourses(
  items: readonly SelectionItem[],
): SelectionGridResult {
  const byKey = new Map<string, { item: SelectionItem; classTime: string[] }>();
  const unplaced: SelectionItem[] = [];
  for (const item of items) {
    if (item.state !== "選上") continue;
    const parsed = item.times === null ? null : parseSchoolTimes(item.times);
    if (parsed === null) {
      unplaced.push(item);
      continue;
    }
    const key = mergeKey(item);
    const existing = byKey.get(key);
    if (existing === undefined) {
      byKey.set(key, { item, classTime: parsed });
      continue;
    }
    for (let day = 0; day < 7; day++) {
      const extra = parsed[day] ?? "";
      if (extra !== "") {
        existing.classTime[day] = unionDaySlots(existing.classTime[day] ?? "", extra);
      }
    }
  }
  const courses = [...byKey.entries()].map(([key, { item, classTime }]) =>
    toCourseOut(item, classTime, key),
  );
  return { courses, unplaced };
}
