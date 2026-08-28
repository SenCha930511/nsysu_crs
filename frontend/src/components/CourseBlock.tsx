import { Trash3 } from "react-bootstrap-icons";

import type { CourseOut } from "../lib/api";

export interface CoursePalette {
  bg: string;
  border: string;
  text: string;
  roomText: string;
  stripe: string;
}

export const COURSE_PALETTES: CoursePalette[] = [
  // 1. Ocean Teal
  { bg: "#f0fdfa", border: "#99f6e4", text: "#0f766e", roomText: "#115e59", stripe: "#0d9488" },
  // 2. Sky Blue
  { bg: "#f0f9ff", border: "#bae6fd", text: "#0369a1", roomText: "#0284c7", stripe: "#0284c7" },
  // 3. Indigo
  { bg: "#eef2ff", border: "#c7d2fe", text: "#4338ca", roomText: "#4f46e5", stripe: "#6366f1" },
  // 4. Purple / Lavender
  { bg: "#faf5ff", border: "#e9d5ff", text: "#6b21a8", roomText: "#7e22ce", stripe: "#9333ea" },
  // 5. Emerald / Mint
  { bg: "#ecfdf5", border: "#a7f3d0", text: "#047857", roomText: "#059669", stripe: "#10b981" },
  // 6. Amber / Honey
  { bg: "#fffbeb", border: "#fde68a", text: "#b45309", roomText: "#d97706", stripe: "#f59e0b" },
  // 7. Rose / Berry
  { bg: "#fff1f2", border: "#fecdd3", text: "#be123c", roomText: "#e11d48", stripe: "#f43f5e" },
  // 8. Cyan / Aqua
  { bg: "#ecfeff", border: "#a5f3fc", text: "#0e7490", roomText: "#0891b2", stripe: "#06b6d4" },
  // 9. Coral / Sunset
  { bg: "#fff7ed", border: "#fed7aa", text: "#c2410c", roomText: "#ea580c", stripe: "#ea580c" },
  // 10. Fuchsia / Blossom
  { bg: "#fdf4ff", border: "#f5d0fe", text: "#a21caf", roomText: "#c026d3", stripe: "#d946ef" },
  // 11. Slate Blue
  { bg: "#f8fafc", border: "#cbd5e1", text: "#334155", roomText: "#475569", stripe: "#64748b" },
  // 12. Lime / Leaf
  { bg: "#f7fee7", border: "#d9f99d", text: "#4d7c0f", roomText: "#65a30d", stripe: "#84cc16" },
];

export function getCoursePalette(input: string): CoursePalette {
  let hash = 0;
  for (let i = 0; i < input.length; i++) {
    hash = input.charCodeAt(i) + ((hash << 5) - hash);
  }
  const index = Math.abs(hash) % COURSE_PALETTES.length;
  return COURSE_PALETTES[index] ?? COURSE_PALETTES[0]!;
}

export function hashLightColor(input: string): string {
  return getCoursePalette(input).bg;
}

export interface CourseBlockProps {
  course: CourseOut;
  hovered: boolean;
  onHover: (courseId: string | null) => void;
  onRemove: (course: CourseOut) => void;
  /** Static preview mode (todo 12 export card): no hover effects, no delete
   * button - the block is a pure visual rendering of the course. */
  readOnly?: boolean;
}

function CourseBlock({
  course,
  hovered,
  onHover,
  onRemove,
  readOnly = false,
}: CourseBlockProps) {
  const name = course.name_zh ?? course.name_en ?? course.code ?? course.id;
  const roomLines = (course.room ?? "")
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);

  const palette = getCoursePalette(course.id + (course.name_zh ?? ""));
  const lit = hovered && !readOnly;

  const style: React.CSSProperties = {
    backgroundColor: lit ? "var(--crs-brand)" : palette.bg,
    color: lit ? "#ffffff" : palette.text,
    border: `1px solid ${lit ? "var(--crs-brand)" : palette.border}`,
    borderLeft: `3.5px solid ${lit ? "#ffffff" : palette.stripe}`,
    boxShadow: lit
      ? "0 4px 12px var(--crs-brand-glow), 0 0 0 2px var(--crs-brand)"
      : "0 1px 3px rgba(0, 0, 0, 0.04)",
  };

  const title = [course.name_zh, course.teacher, course.room]
    .filter((part) => part !== null && part !== "")
    .join(" / ");

  return (
    <div
      className="course-block"
      style={style}
      title={title}
      {...(readOnly
        ? {}
        : {
            onMouseEnter: () => onHover(course.id),
            onMouseLeave: () => onHover(null),
          })}
    >
      <span className="course-block-title">{name}</span>
      {roomLines.map((room, index) => (
        <span
          key={`room-${index}`}
          className="course-block-room"
          style={{ color: lit ? "rgba(255, 255, 255, 0.9)" : palette.roomText }}
        >
          {room}
        </span>
      ))}
      {!readOnly && (
        <button
          type="button"
          className="course-block-delete"
          aria-label={`移除 ${name}`}
          onClick={(event) => {
            event.stopPropagation();
            onRemove(course);
          }}
        >
          <Trash3 size={9} />
        </button>
      )}
    </div>
  );
}

export default CourseBlock;

