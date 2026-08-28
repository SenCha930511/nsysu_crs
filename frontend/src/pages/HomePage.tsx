import { useRef, useState } from "react";
import { ArrowRepeat, CalendarCheck, Download } from "react-bootstrap-icons";

import CourseBrowser from "../components/CourseBrowser";
import ScheduleTable from "../components/ScheduleTable";
import TotalsPanel from "../components/TotalsPanel";
import { downloadGridPng } from "../lib/export";
import { usePlansSync } from "../state/plansSync";
import { useSelection } from "../state/selection";

function HomePage() {
  const { selected, remove } = useSelection();
  const [hoveredCourseId, setHoveredCourseId] = useState<string | null>(null);
  const gridRef = useRef<HTMLDivElement>(null);
  const [pngState, setPngState] = useState<"idle" | "busy">("idle");
  const [pngError, setPngError] = useState<string | null>(null);
  const sync = usePlansSync();
  const activePlan =
    sync.plans.find((p) => p.id === sync.activePlanId) ?? null;
  // Courses that actually land in grid cells (placeholder rows with no
  // time data render nothing and must count as empty for the guard).
  const visualCount = selected.filter(
    (course) =>
      course.class_time !== null &&
      course.class_time.some((slot) => slot !== ""),
  ).length;

  const onPng = () => {
    const node = gridRef.current;
    if (node === null || pngState === "busy") return;
    setPngError(null);
    setPngState("busy");
    downloadGridPng(node, activePlan?.name ?? null, visualCount)
      .catch((err: unknown) =>
        setPngError(err instanceof Error ? err.message : String(err)),
      )
      .finally(() => setPngState("idle"));
  };

  return (
    <div className="row g-3">
      <div className="col-12 col-lg-7">
        <CourseBrowser
          hoveredCourseId={hoveredCourseId}
          onCourseHover={setHoveredCourseId}
        />
      </div>
      <div className="col-12 col-lg-5">
        <div className="schedule-side">
          <div className="d-flex justify-content-between align-items-center mb-2 px-1">
            <div className="d-flex align-items-center gap-1.5">
              <CalendarCheck className="text-teal-600" size={16} />
              <span className="fw-bold text-dark" style={{ fontSize: "0.95rem" }}>
                {activePlan?.name ? `課表：${activePlan.name}` : "目前預覽課表"}
              </span>
            </div>
            <button
              type="button"
              className="btn btn-sm btn-outline-brand d-inline-flex align-items-center gap-1 shadow-sm"
              disabled={pngState === "busy"}
              onClick={onPng}
            >
              {pngState === "busy" ? (
                <>
                  <ArrowRepeat className="spinner-border spinner-border-sm" aria-hidden />
                  <span>匯出中…</span>
                </>
              ) : (
                <>
                  <Download size={13} aria-hidden />
                  <span>下載課表 PNG</span>
                </>
              )}
            </button>
          </div>
          {pngError !== null && (
            <div className="alert alert-warning py-1.5 px-3 small rounded-3 mb-2" role="alert">
              {pngError}
            </div>
          )}
          <TotalsPanel selectedCourses={selected} />
          <div ref={gridRef}>
            <ScheduleTable
              selectedCourses={selected}
              hoveredCourseId={hoveredCourseId}
              onCourseHover={setHoveredCourseId}
              onCourseRemove={(course) => remove(course.id)}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

export default HomePage;

