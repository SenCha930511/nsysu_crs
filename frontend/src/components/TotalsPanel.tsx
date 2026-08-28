import { useMemo } from "react";
import { Award, Book, Clock, ExclamationTriangleFill } from "react-bootstrap-icons";

import { conflictPairs } from "../lib/conflicts";
import { totalCreditsAndHours } from "../lib/totals";
import type { CourseOut } from "../lib/api";

export interface TotalsPanelProps {
  selectedCourses: readonly CourseOut[];
  onDownloadPng?: () => void;
  isDownloadingPng?: boolean;
}

function courseName(course: CourseOut): string {
  return course.name_zh ?? course.name_en ?? course.id;
}

function TotalsPanel({
  selectedCourses,
  onDownloadPng,
  isDownloadingPng = false,
}: TotalsPanelProps) {
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
    <div className="floating-stats-dock" aria-label="選課統計懸浮資訊">
      <div className="dock-stat-item">
        <Book size={14} className="text-teal-400" />
        <span>已選 {totals.courseCount} 門</span>
      </div>
      <div className="dock-divider" />
      <div className="dock-stat-item">
        <Award size={14} className="text-cyan-400" />
        <span>總學分 {totals.totalCredits}</span>
      </div>
      <div className="dock-divider" />
      <div className="dock-stat-item">
        <Clock size={14} className="text-indigo-300" />
        <span>{totals.totalHours} 節</span>
      </div>

      {pairs.length > 0 && (
        <>
          <div className="dock-divider" />
          <div className="dock-stat-item text-danger fw-bold" title={conflictTitle}>
            <ExclamationTriangleFill size={14} className="text-warning" />
            <span>衝堂 {pairs.length} 組</span>
          </div>
        </>
      )}

      {onDownloadPng && (
        <>
          <div className="dock-divider" />
          <button
            type="button"
            className="dock-action-btn dock-action-btn-brand"
            disabled={isDownloadingPng}
            onClick={onDownloadPng}
          >
            {isDownloadingPng ? "匯出中…" : "下載課表圖"}
          </button>
        </>
      )}
    </div>
  );
}

export default TotalsPanel;
