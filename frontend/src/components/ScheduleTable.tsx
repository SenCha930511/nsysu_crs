/**
 * Weekly timetable grid: 15 period rows x 7 weekday columns.
 *
 * Adapted from NSYSU-OpenDev/NSYSUSelectorHelper (MIT License,
 * Copyright (c) Cellery Lin and whats2000):
 *   client-website/src/components/ScheduleTable.tsx
 *   https://github.com/NSYSU-OpenDev/NSYSUSelectorHelper
 *
 * Kept from upstream: a plain HTML table keyed weekday-timeslot, multiple
 * course blocks per cell, weekend columns shaded gray, hover-synced course
 * blocks. Our timeslot config and conflict layer come from our own
 * config/timeslots.ts; corrupt day strings (unknown codes) land in a visible
 * error strip instead of crashing the page.
 */

import { useMemo } from "react";

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

function ScheduleTable({
  selectedCourses,
  hoveredCourseId,
  onCourseHover,
  onCourseRemove,
  readOnly = false,
}: ScheduleTableProps) {
  const { cells, invalid } = useMemo(
    () => buildGrid(selectedCourses),
    [selectedCourses],
  );

  return (
    <div className="schedule-wrapper">
      {invalid.length > 0 && (
        <div className="alert alert-danger py-1 px-2 small" role="alert">
          {invalid.length} 門課程時間資料異常，未排入課表：
          {invalid.map((c) => c.name_zh ?? c.id).join("、")}
        </div>
      )}
      <div className="table-responsive">
        <table className="schedule-table table table-bordered text-center align-middle mb-0">
          <thead>
            <tr>
              <th scope="col" className="schedule-timeslot-col">
                節
              </th>
              {WEEKDAYS.map((day) => (
                <th
                  key={day.index}
                  scope="col"
                  className={day.index >= 5 ? "table-secondary" : undefined}
                >
                  {day.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {TIMESLOTS.map((timeslot, rowIndex) => (
              <tr key={timeslot.code}>
                <th scope="row" className="schedule-timeslot-col">
                  <span className="d-block fw-bold">{timeslot.code}</span>
                  <span className="schedule-clock">
                    {timeslot.start}–{timeslot.end}
                  </span>
                </th>
                {WEEKDAYS.map((day, dayIndex) => (
                  <td
                    key={`${day.index}-${timeslot.code}`}
                    className={day.index >= 5 ? "schedule-weekend" : undefined}
                  >
                    {(cells[rowIndex]?.[dayIndex] ?? []).map((course) => (
                      <CourseBlock
                        key={course.id}
                        course={course}
                        hovered={hoveredCourseId === course.id}
                        onHover={onCourseHover}
                        onRemove={onCourseRemove}
                        readOnly={readOnly}
                      />
                    ))}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default ScheduleTable;
