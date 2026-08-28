import { Trash3 } from "react-bootstrap-icons";

import type { CourseOut } from "../lib/api";

export type CourseCategory = "compulsory" | "elective" | "general" | "other";

export interface CoursePalette {
  category: CourseCategory;
  categoryLabel: string;
  bg: string;
  border: string;
  text: string;
  roomText: string;
  stripe: string;
}

export const CATEGORY_PALETTES: Record<CourseCategory, CoursePalette> = {
  // 1. 必修 (Compulsory): Sky / Ocean Blue
  compulsory: {
    category: "compulsory",
    categoryLabel: "必修",
    bg: "#f0f9ff",
    border: "#bae6fd",
    text: "#0369a1",
    roomText: "#0284c7",
    stripe: "#0284c7",
  },
  // 2. 選修 (Elective): Fresh Mint / Emerald Green
  elective: {
    category: "elective",
    categoryLabel: "選修",
    bg: "#f0fdf4",
    border: "#bbf7d0",
    text: "#166534",
    roomText: "#15803d",
    stripe: "#16a34a",
  },
  // 3. 通識 / 共同 / EMI (General / Other): Lavender / Purple
  general: {
    category: "general",
    categoryLabel: "通識",
    bg: "#faf5ff",
    border: "#e9d5ff",
    text: "#6b21a8",
    roomText: "#7e22ce",
    stripe: "#9333ea",
  },
  // 4. 其他 (Other): Soft Warm Slate
  other: {
    category: "other",
    categoryLabel: "其他",
    bg: "#f8fafc",
    border: "#cbd5e1",
    text: "#334155",
    roomText: "#475569",
    stripe: "#64748b",
  },
};

export function getCourseCategory(course: CourseOut): CourseCategory {
  const dept = course.dept ?? "";
  const name = course.name_zh ?? "";
  
  if (
    dept.includes("通識") ||
    dept.includes("博雅") ||
    name.includes("通識") ||
    name.includes("體育") ||
    name.includes("國文") ||
    name.includes("英文") ||
    name.includes("跨領域") ||
    course.english === true
  ) {
    return "general";
  }
  if (course.compulsory === true) {
    return "compulsory";
  }
  if (course.compulsory === false) {
    return "elective";
  }
  return "other";
}

export function getCoursePalette(courseOrInput: CourseOut | string): CoursePalette {
  if (typeof courseOrInput === "object" && courseOrInput !== null) {
    const cat = getCourseCategory(courseOrInput);
    return CATEGORY_PALETTES[cat];
  }
  return CATEGORY_PALETTES.compulsory;
}

export function hashLightColor(_input: string): string {
  return CATEGORY_PALETTES.compulsory.bg;
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

  const palette = getCoursePalette(course);
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

  const title = [
    course.name_zh,
    palette.categoryLabel,
    course.teacher,
    course.room,
  ]
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

