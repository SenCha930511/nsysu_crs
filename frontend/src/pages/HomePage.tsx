/** Home: the todo-10 read-only core (course browser + weekly timetable). */

import { useState } from "react";

import CourseBrowser from "../components/CourseBrowser";
import ScheduleTable from "../components/ScheduleTable";
import TotalsPanel from "../components/TotalsPanel";
import { useSelection } from "../state/selection";

function HomePage() {
  const { selected, remove } = useSelection();
  const [hoveredCourseId, setHoveredCourseId] = useState<string | null>(null);

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
  );
}

export default HomePage;
