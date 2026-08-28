import { useMemo } from "react";
import { Award, Book, Clock, ExclamationTriangleFill } from "react-bootstrap-icons";

import { conflictPairs } from "../lib/conflicts";
import { useI18n } from "../lib/i18n";
import { totalCreditsAndHours } from "../lib/totals";
import type { CourseOut } from "../lib/api";

export interface TotalsPanelProps {
  selectedCourses: readonly CourseOut[];
  onDownloadPng?: () => void;
  isDownloadingPng?: boolean;
  className?: string;
}

function courseName(course: CourseOut): string {
  return course.name_zh ?? course.name_en ?? course.id;
}

function TotalsPanel({
  selectedCourses,
  onDownloadPng,
  isDownloadingPng = false,
  className = "top-stats-dock",
}: TotalsPanelProps) {
  const { tx } = useI18n();
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
    <div className={className} aria-label={tx("選課統計懸浮資訊", "Selection statistics dock")}>
      <div className="dock-stat-item">
        <Book size={14} className="text-teal-400" />
        <span>{tx(`已選 ${totals.courseCount} 門`, `${totals.courseCount} course(s)`)}</span>
      </div>
      <div className="dock-divider" />
      <div className="dock-stat-item">
        <Award size={14} className="text-cyan-400" />
        <span>{tx(`總學分 ${totals.totalCredits}`, `${totals.totalCredits} credits`)}</span>
      </div>
      <div className="dock-divider" />
      <div className="dock-stat-item">
        <Clock size={14} className="text-indigo-300" />
        <span>{tx(`${totals.totalHours} 節`, `${totals.totalHours} periods`)}</span>
      </div>

      {pairs.length > 0 && (
        <>
          <div className="dock-divider" />
          <div className="dock-stat-item text-danger fw-bold" title={conflictTitle}>
            <ExclamationTriangleFill size={14} className="text-warning" />
            <span>{tx(`衝堂 ${pairs.length} 組`, `${pairs.length} clash(es)`)}</span>
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
            {isDownloadingPng ? tx("匯出中…", "Exporting…") : tx("下載課表圖", "Download PNG")}
          </button>
        </>
      )}
    </div>
  );
}

export default TotalsPanel;
