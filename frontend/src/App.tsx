import { useState } from "react";

import CourseBrowser from "./components/CourseBrowser";
import DegradeBanner from "./components/DegradeBanner";
import ScheduleTable from "./components/ScheduleTable";
import TotalsPanel from "./components/TotalsPanel";
import { SelectionProvider, useSelection } from "./state/selection";

/**
 * Read-only core (plan todo 10): course browser on the left, weekly
 * timetable on the right. Hover sync (list row <-> grid blocks) is keyed by
 * course id in this shell. Login / server plans (todo 11), export (todo 12)
 * and write paths (todo 16) are deliberately absent.
 */
function Shell() {
  const { selected, remove } = useSelection();
  const [hoveredCourseId, setHoveredCourseId] = useState<string | null>(null);

  return (
    <>
      <DegradeBanner />
      <header className="app-header">
        <h1 className="h5 mb-0 fw-bold text-white">中山選課小幫手</h1>
        <span className="app-header-sub small">NSYSU Course Wrapper · 115-1</span>
      </header>
      <main className="container-fluid px-3 py-3">
        <div className="row g-3">
          <div className="col-12 col-lg-7">
            <CourseBrowser
              hoveredCourseId={hoveredCourseId}
              onCourseHover={setHoveredCourseId}
            />
          </div>
          <div className="col-12 col-lg-5">
            <div className="schedule-side">
              <TotalsPanel selectedCourses={selected} />
              <ScheduleTable
                selectedCourses={selected}
                hoveredCourseId={hoveredCourseId}
                onCourseHover={setHoveredCourseId}
                onCourseRemove={(course) => remove(course.id)}
              />
            </div>
          </div>
        </div>
      </main>
    </>
  );
}

function App() {
  return (
    <SelectionProvider>
      <Shell />
    </SelectionProvider>
  );
}

export default App;
