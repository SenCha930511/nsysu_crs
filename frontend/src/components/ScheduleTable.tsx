import { useMemo, useState } from "react";

import { TIMESLOTS, WEEKDAYS, parseDayTimeString } from "../config/timeslots";
import type { CourseOut } from "../lib/api";
import { useI18n } from "../lib/i18n";
import CourseBlock from "./CourseBlock";

export interface ScheduleTableProps {
  selectedCourses: readonly CourseOut[];
  hoveredCourseId: string | null;
  onCourseHover: (courseId: string | null) => void;
  onCourseRemove: (course: CourseOut) => void;
  /** Static render (todo 12 export preview): blocks show no hover visuals
   * and no delete buttons; hover/remove callbacks are never invoked. */
  readOnly?: boolean;
  /** Optional ghost preview of a hovered course from discovery list */
  previewCourse?: CourseOut | null;
}

interface CellItem {
  type: "render" | "skip";
  rowSpan?: number | undefined;
  spanCount?: number | undefined;
  timeRange?: string | undefined;
  courses: CourseOut[];
}

const DAY_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function getGhostSlots(course: CourseOut | null | undefined): Set<string> {
  if (!course || !course.class_time) return new Set();
  const set = new Set<string>();
  try {
    WEEKDAYS.forEach((weekday, dayIndex) => {
      const dayStr = course.class_time?.[weekday.index] ?? "";
      if (dayStr) {
        const codes = parseDayTimeString(dayStr);
        codes.forEach((code) => {
          set.add(`${dayIndex}-${code}`);
        });
      }
    });
  } catch {
    // ignore parsing errors on ghost preview
  }
  return set;
}

function ScheduleTable({
  selectedCourses,
  hoveredCourseId,
  onCourseHover,
  onCourseRemove,
  readOnly = false,
  previewCourse = null,
}: ScheduleTableProps) {
  const { lang, tx } = useI18n();
  const [showWeekends, setShowWeekends] = useState(false);

  const displayedWeekdays = showWeekends
    ? WEEKDAYS
    : WEEKDAYS.filter((d) => d.index < 5);

  // Validate courses
  const { validCourses, invalid } = useMemo(() => {
    const valid: CourseOut[] = [];
    const bad: CourseOut[] = [];
    for (const course of selectedCourses) {
      try {
        const time = course.class_time ?? [];
        WEEKDAYS.forEach((day) => parseDayTimeString(time[day.index] ?? ""));
        valid.push(course);
      } catch {
        bad.push(course);
      }
    }
    return { validCourses: valid, invalid: bad };
  }, [selectedCourses]);

  const ghostSlots = useMemo(
    () => getGhostSlots(previewCourse),
    [previewCourse],
  );

  // Build grid matrix with contiguous span calculation
  const gridPlan = useMemo(() => {
    const numRows = TIMESLOTS.length;
    const numDays = WEEKDAYS.length;

    // 1. Raw cell occupancy: rawGrid[rowIndex][dayIndex] = CourseOut[]
    const rawGrid: CourseOut[][][] = Array.from({ length: numRows }, () =>
      Array.from({ length: numDays }, () => []),
    );

    for (const course of validCourses) {
      const time = course.class_time ?? [];
      WEEKDAYS.forEach((weekday, dayIndex) => {
        const dayStr = time[weekday.index] ?? "";
        if (!dayStr) return;
        const codes = parseDayTimeString(dayStr);
        TIMESLOTS.forEach((timeslot, rowIndex) => {
          if (codes.has(timeslot.code)) {
            const cellList = rawGrid[rowIndex]?.[dayIndex];
            if (cellList) {
              cellList.push(course);
            }
          }
        });
      });
    }

    // 2. Matrix of CellItem plans for [rowIndex][dayIndex]
    const planMatrix: CellItem[][] = Array.from({ length: numRows }, () =>
      Array.from({ length: numDays }, () => ({ type: "render", rowSpan: 1, courses: [] })),
    );

    for (let dayIndex = 0; dayIndex < numDays; dayIndex++) {
      // Check contiguous blocks for single-occupancy courses
      let rowIndex = 0;
      while (rowIndex < numRows) {
        const rowData = rawGrid[rowIndex];
        const cellCourses = rowData?.[dayIndex] ?? [];

        if (cellCourses.length === 1) {
          const singleCourse = cellCourses[0];
          if (!singleCourse) {
            rowIndex++;
            continue;
          }
          // Check how many contiguous rows this same single course occupies
          let span = 1;
          while (
            rowIndex + span < numRows &&
            (rawGrid[rowIndex + span]?.[dayIndex]?.length ?? 0) === 1 &&
            rawGrid[rowIndex + span]?.[dayIndex]?.[0]?.id === singleCourse.id
          ) {
            span++;
          }

          const startSlot = TIMESLOTS[rowIndex];
          const endSlot = TIMESLOTS[rowIndex + span - 1];
          const timeRange =
            startSlot && endSlot ? `${startSlot.start}–${endSlot.end}` : undefined;

          const currRow = planMatrix[rowIndex];
          if (currRow) {
            currRow[dayIndex] = {
              type: "render",
              rowSpan: span,
              spanCount: span,
              timeRange,
              courses: [singleCourse],
            };
          }

          for (let s = 1; s < span; s++) {
            const skipRow = planMatrix[rowIndex + s];
            if (skipRow) {
              skipRow[dayIndex] = { type: "skip", courses: [] };
            }
          }
          rowIndex += span;
        } else {
          // Empty cell or Clash cell
          const currRow = planMatrix[rowIndex];
          if (currRow) {
            currRow[dayIndex] = {
              type: "render",
              rowSpan: 1,
              spanCount: 1,
              courses: cellCourses,
            };
          }
          rowIndex++;
        }
      }
    }

    return { planMatrix };
  }, [validCourses]);

  return (
    <div className="schedule-table-wrapper w-100">
      {invalid.length > 0 && (
        <div className="alert alert-danger py-1.5 px-3 small rounded-3 mb-2" role="alert">
          {tx(
            `${invalid.length} 門課程時間資料異常，未排入課表：`,
            `${invalid.length} course(s) have bad time data and were left off the grid: `,
          )}
          {invalid.map((c) => c.name_zh ?? c.id).join("、")}
        </div>
      )}

      {/* Top Bar: Category Legend & Weekday toggle */}
      <div className="d-flex align-items-center justify-content-between mb-2 px-1 flex-wrap gap-2">
        <div className="d-flex align-items-center gap-3" style={{ fontSize: "0.84rem" }}>
          <span className="d-inline-flex align-items-center" style={{ gap: "0.45rem" }}>
            <span style={{ width: "9px", height: "9px", borderRadius: "50%", background: "#0284c7" }} />
            <span className="text-secondary fw-semibold">{tx("必修", "Required")}</span>
          </span>
          <span className="d-inline-flex align-items-center" style={{ gap: "0.45rem" }}>
            <span style={{ width: "9px", height: "9px", borderRadius: "50%", background: "#16a34a" }} />
            <span className="text-secondary fw-semibold">{tx("選修", "Elective")}</span>
          </span>
          <span className="d-inline-flex align-items-center" style={{ gap: "0.45rem" }}>
            <span style={{ width: "9px", height: "9px", borderRadius: "50%", background: "#9333ea" }} />
            <span className="text-secondary fw-semibold">{tx("通識/其他", "GE/Other")}</span>
          </span>
        </div>

        <div className="schedule-view-toggler">
          <button
            type="button"
            className={`view-toggle-btn ${!showWeekends ? "active" : ""}`}
            onClick={() => setShowWeekends(false)}
          >
            {tx("週一至五", "Mon–Fri")}
          </button>
          <button
            type="button"
            className={`view-toggle-btn ${showWeekends ? "active" : ""}`}
            onClick={() => setShowWeekends(true)}
          >
            {tx("完整一週 (含週末)", "Full week (incl. weekends)")}
          </button>
        </div>
      </div>

      <div className="table-responsive">
        <table className="studio-schedule-table table text-center align-middle mb-0">
          <colgroup>
            <col style={{ width: "4.8rem" }} />
            {displayedWeekdays.map((day) => (
              <col key={day.index} />
            ))}
          </colgroup>
          <thead>
            <tr>
              <th scope="col" className="studio-timeslot-header">
                <div>{tx("時間 / 節次", "Time / Period")}</div>
              </th>
              {displayedWeekdays.map((day) => (
                <th
                  key={day.index}
                  scope="col"
                  className={`schedule-day-header ${day.index >= 5 ? "schedule-weekend" : ""}`}
                >
                  <div className="day-header-title">週{day.label}</div>
                  <div className="day-header-sub">
                    {lang === "en" ? DAY_EN[day.index] : `星期${day.label}`}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {TIMESLOTS.map((timeslot, rowIndex) => (
              <tr key={timeslot.code}>
                <th scope="row" className="studio-timeslot-header">
                  <div className="timeslot-code-chip">{timeslot.code}</div>
                  <div className="timeslot-clock-sub">{timeslot.start}</div>
                </th>
                {displayedWeekdays.map((day) => {
                  const dayIndex = day.index;
                  const plan = gridPlan.planMatrix[rowIndex]?.[dayIndex];

                  if (plan?.type === "skip") {
                    return null;
                  }

                  const coursesInCell = plan?.courses ?? [];
                  const isGhostCell =
                    ghostSlots.has(`${dayIndex}-${timeslot.code}`) &&
                    !coursesInCell.some((c) => c.id === previewCourse?.id);

                  return (
                    <td
                      key={`${day.index}-${timeslot.code}`}
                      rowSpan={plan?.rowSpan ?? 1}
                      className={day.index >= 5 ? "schedule-weekend" : undefined}
                    >
                      {coursesInCell.map((course) => (
                        <CourseBlock
                          key={course.id}
                          course={course}
                          hovered={hoveredCourseId === course.id}
                          onHover={onCourseHover}
                          onRemove={onCourseRemove}
                          readOnly={readOnly}
                          spanCount={plan?.spanCount ?? 1}
                          timeRange={plan?.timeRange}
                        />
                      ))}
                      {isGhostCell && previewCourse && (
                        <div className="course-block-ghost" title={tx("預覽時段", "Preview slot")}>
                          <span>{previewCourse.name_zh ?? previewCourse.name_en}</span>
                        </div>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default ScheduleTable;
