/**
 * Credit / hours totals + conflict summary for the current selection.
 * Data comes from lib/totals.ts and lib/conflicts.ts (both adapted from
 * NSYSUSelectorHelper, see those files for attribution).
 */

import { useMemo } from "react";

import { conflictPairs } from "../lib/conflicts";
import { totalCreditsAndHours } from "../lib/totals";
import type { CourseOut } from "../lib/api";

export interface TotalsPanelProps {
  selectedCourses: readonly CourseOut[];
}

function courseName(course: CourseOut): string {
  return course.name_zh ?? course.name_en ?? course.id;
}

function TotalsPanel({ selectedCourses }: TotalsPanelProps) {
  const totals = useMemo(
    () => totalCreditsAndHours(selectedCourses),
    [selectedCourses],
  );
  const pairs = useMemo(() => conflictPairs(selectedCourses), [selectedCourses]);

  const conflictTitle = pairs
    .map(
      (p) =>
        `${courseName(p.a)} × ${courseName(p.b)}（${p.slotTags.join(" ")}）`,
    )
    .join("\n");

  return (
    <div className="totals-panel">
      <span className="badge text-bg-light border">已選 {totals.courseCount} 門</span>
      <span className="badge text-bg-primary">總學分 {totals.totalCredits}</span>
      <span className="badge text-bg-info">總時數 {totals.totalHours} 節</span>
      {pairs.length > 0 && (
        <span className="badge text-bg-danger" title={conflictTitle}>
          衝堂 {pairs.length} 組
        </span>
      )}
    </div>
  );
}

export default TotalsPanel;
