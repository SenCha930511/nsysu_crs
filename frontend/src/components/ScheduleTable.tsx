import { useMemo, useState } from "react";

import { TIMESLOTS, WEEKDAYS, parseDayTimeString } from "../config/timeslots";
import type { CourseOut } from "../lib/api";
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

interface GridModel {
  /** cells[rowIndex][dayIndex] = courses occupying that grid cell. */
  cells: CourseOut[][][];
  /** Courses whose class_time failed validation (shown above the table). */
  invalid: CourseOut[];
}

function buildGrid(selectedCourses: readonly CourseOut[]): GridModel {
  const cells: CourseOut[][][] = TIMESLOTS.map(() =>
    WEEKDAYS.map(() => []),
  );
  const invalid: CourseOut[] = [];

  for (const course of selectedCourses) {
    let dayCodes: ReadonlySet<string>[];
    try {
      const time = course.class_time ?? [];
      dayCodes = WEEKDAYS.map((day) => parseDayTimeString(time[day.index] ?? ""));
    } catch (error) {
      console.error("course class_time rejected:", course.id, error);
      invalid.push(course);
      continue;
    }
    TIMESLOTS.forEach((timeslot, rowIndex) => {
      WEEKDAYS.forEach((weekday, dayIndex) => {
        if (dayCodes[weekday.index]?.has(timeslot.code) === true) {
          const cell = cells[rowIndex]?.[dayIndex];
          cell?.push(course);
        }
      });
    });
  }
  return { cells, invalid };
}

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
  const [showWeekends, setShowWeekends] = useState(false);
  const { cells, invalid } = useMemo(
    () => buildGrid(selectedCourses),
    [selectedCourses],
  );

  const ghostSlots = useMemo(
    () => getGhostSlots(previewCourse),
    [previewCourse],
  );

  const displayedWeekdays = showWeekends
    ? WEEKDAYS
    : WEEKDAYS.filter((d) => d.index < 5);

  return (
    <div className="schedule-table-wrapper w-100">
      {invalid.length > 0 && (
        <div className="alert alert-danger py-1.5 px-3 small rounded-3 mb-2" role="alert">
          {invalid.length} 門課程時間資料異常，未排入課表：
          {invalid.map((c) => c.name_zh ?? c.id).join("、")}
        </div>
      )}

      {/* Top Bar: Category Legend & Weekday toggle */}
      <div className="d-flex align-items-center justify-content-between mb-1.5 px-1 flex-wrap gap-2">
        <div className="d-flex align-items-center gap-2.5" style={{ fontSize: "0.74rem" }}>
          <span className="d-inline-flex align-items-center gap-1.5">
            <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#0284c7" }} />
            <span className="text-secondary fw-semibold">必修</span>
          </span>
          <span className="d-inline-flex align-items-center gap-1.5">
            <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#16a34a" }} />
            <span className="text-secondary fw-semibold">選修</span>
          </span>
          <span className="d-inline-flex align-items-center gap-1.5">
            <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#9333ea" }} />
            <span className="text-secondary fw-semibold">通識/其他</span>
          </span>
        </div>

        <div className="schedule-view-toggler">
          <button
            type="button"
            className={`view-toggle-btn ${!showWeekends ? "active" : ""}`}
            onClick={() => setShowWeekends(false)}
          >
            週一至五
          </button>
          <button
            type="button"
            className={`view-toggle-btn ${showWeekends ? "active" : ""}`}
            onClick={() => setShowWeekends(true)}
          >
            完整一週 (含週末)
          </button>
        </div>
      </div>

      <div className="table-responsive">
        <table className="studio-schedule-table table text-center align-middle mb-0">
          <colgroup>
            <col style={{ width: "4rem" }} />
            {displayedWeekdays.map((day) => (
              <col key={day.index} />
            ))}
          </colgroup>
          <thead>
            <tr>
              <th scope="col" className="studio-timeslot-header">
                節次
              </th>
              {displayedWeekdays.map((day) => (
                <th
                  key={day.index}
                  scope="col"
                  className={day.index >= 5 ? "schedule-weekend" : undefined}
                >
                  週{day.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {TIMESLOTS.map((timeslot, rowIndex) => (
              <tr key={timeslot.code}>
                <th scope="row" className="studio-timeslot-header">
                  <span className="timeslot-code-chip">{timeslot.code}</span>
                  <span className="timeslot-clock-sub">
                    {timeslot.start}–{timeslot.end}
                  </span>
                </th>
                {displayedWeekdays.map((day) => {
                  const dayIndex = day.index;
                  const coursesInCell = cells[rowIndex]?.[dayIndex] ?? [];
                  const isGhostCell =
                    ghostSlots.has(`${dayIndex}-${timeslot.code}`) &&
                    !coursesInCell.some((c) => c.id === previewCourse?.id);

                  return (
                    <td
                      key={`${day.index}-${timeslot.code}`}
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
                        />
                      ))}
                      {isGhostCell && previewCourse && (
                        <div className="course-block-ghost" title="預覽時段">
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
