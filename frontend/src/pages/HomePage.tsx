import { useRef, useState } from "react";
import { CalendarCheck } from "react-bootstrap-icons";

import CourseBrowser from "../components/CourseBrowser";
import ScheduleTable from "../components/ScheduleTable";
import TotalsPanel from "../components/TotalsPanel";
import type { CourseOut } from "../lib/api";
import { downloadGridPng } from "../lib/export";
import { usePlansSync } from "../state/plansSync";
import { useSelection } from "../state/selection";

function HomePage() {
  const { selected, remove } = useSelection();
  const [hoveredCourseId, setHoveredCourseId] = useState<string | null>(null);
  const [previewCourse, setPreviewCourse] = useState<CourseOut | null>(null);
  const gridRef = useRef<HTMLDivElement>(null);
  const [pngState, setPngState] = useState<"idle" | "busy">("idle");
  const [pngError, setPngError] = useState<string | null>(null);
  const sync = usePlansSync();
  const activePlan =
    sync.plans.find((p) => p.id === sync.activePlanId) ?? null;

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
      {/* Left Pane: Smart Schedule Canvas & Timetable */}
      <div className="col-12 col-xl-7">
        <div className="schedule-canvas-pane">
          {/* Canvas Header */}
          <div className="schedule-canvas-header">
            <div className="schedule-canvas-title">
              <CalendarCheck size={17} className="text-teal-600" />
              <span>{activePlan?.name ? `課表畫布：${activePlan.name}` : "智慧課表畫布"}</span>
            </div>
          </div>

          {pngError !== null && (
            <div className="alert alert-warning py-1.5 px-3 mx-3 mt-2 small rounded-3" role="alert">
              {pngError}
            </div>
          )}

          {/* Schedule Table Container */}
          <div className="schedule-grid-scroll-container" ref={gridRef}>
            <ScheduleTable
              selectedCourses={selected}
              hoveredCourseId={hoveredCourseId}
              onCourseHover={setHoveredCourseId}
              onCourseRemove={(course) => remove(course.id)}
              previewCourse={previewCourse}
            />
          </div>

          {/* Floating Stats HUD Dock */}
          <TotalsPanel
            selectedCourses={selected}
            onDownloadPng={onPng}
            isDownloadingPng={pngState === "busy"}
          />
        </div>
      </div>

      {/* Right Pane: Course Discovery Studio */}
      <div className="col-12 col-xl-5">
        <CourseBrowser
          hoveredCourseId={hoveredCourseId}
          onCourseHover={setHoveredCourseId}
          onCoursePreview={setPreviewCourse}
        />
      </div>
    </div>
  );
}

export default HomePage;
