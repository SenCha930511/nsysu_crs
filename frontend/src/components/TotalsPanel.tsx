import { useMemo } from "react";
import { Award, Book, Clock, ExclamationTriangleFill } from "react-bootstrap-icons";

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
    <div className="totals-panel" aria-label="選課統計">
      <div className="stat-chip stat-chip-count">
        <Book size={13} />
        <span>已選 {totals.courseCount} 門</span>
      </div>
      <div className="stat-chip stat-chip-credits">
        <Award size={14} />
        <span>總學分 {totals.totalCredits}</span>
      </div>
      <div className="stat-chip stat-chip-hours">
        <Clock size={13} />
        <span>總時數 {totals.totalHours} 節</span>
      </div>
      {pairs.length > 0 && (
        <div className="stat-chip stat-chip-conflict" title={conflictTitle}>
          <ExclamationTriangleFill size={13} />
          <span>衝堂 {pairs.length} 組</span>
        </div>
      )}
    </div>
  );
}

export default TotalsPanel;

