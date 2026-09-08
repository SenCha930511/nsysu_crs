import { GeoAltFill, PersonFill, Trash3 } from "react-bootstrap-icons";

import type { CourseOut } from "../lib/api";
import { useI18n } from "../lib/i18n";

export type CourseCategory = "compulsory" | "elective" | "general" | "other";

export interface CoursePalette {
  category: CourseCategory;
  categoryLabel: string;
  bg: string;
  badgeBg: string;
  badgeText: string;
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
    badgeBg: "#e0f2fe",
    badgeText: "#0369a1",
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
    badgeBg: "#dcfce7",
    badgeText: "#15803d",
    border: "#bbf7d0",
    text: "#166534",
    roomText: "#15803d",
    stripe: "#16a34a",
  },
  // 3. 通識 / 共同 / EMI (General / Other): Lavender / Purple
  general: {
    category: "general",
    categoryLabel: "通識",
    badgeBg: "#f3e8ff",
    badgeText: "#7e22ce",
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
    badgeBg: "#f1f5f9",
    badgeText: "#334155",
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
  /** Fires when the user wants the course's detail sheet (name click). */
  onViewCourse?: ((course: CourseOut) => void) | undefined;
  /** Number of periods spanned in this contiguous block */
  spanCount?: number | undefined;
  /** Clock range string (e.g. "09:10-12:00") */
  timeRange?: string | undefined;
}

function CourseBlock({
  course,
  hovered,
  onHover,
  onRemove,
  readOnly = false,
  spanCount = 1,
  timeRange,
  onViewCourse,
}: CourseBlockProps) {
  const { lang, tx } = useI18n();
  const name = course.name_zh ?? course.name_en ?? course.code ?? course.id;
  const teacher = (course.teacher ?? "").trim();
  const room = (course.room ?? "").trim();

  const palette = getCoursePalette(course);
  const lit = hovered && !readOnly;
  const EN_CATEGORY: Record<CourseCategory, string> = {
    compulsory: "Required",
    elective: "Elective",
    general: "GE",
    other: "Other",
  };
  const categoryLabel = lang === "en" ? EN_CATEGORY[palette.category] : palette.categoryLabel;

  const style: React.CSSProperties = {
    backgroundColor: lit ? "var(--crs-brand)" : palette.bg,
    color: lit ? "#ffffff" : palette.text,
    border: `1.5px solid ${lit ? "var(--crs-brand)" : palette.border}`,
    borderLeft: `4px solid ${lit ? "#ffffff" : palette.stripe}`,
    boxShadow: lit
      ? "0 4px 14px var(--crs-brand-glow), 0 0 0 2px var(--crs-brand)"
      : "0 1px 3px rgba(0, 0, 0, 0.04)",
  };

  const title = [
    course.name_zh,
    categoryLabel,
    course.teacher,
    course.room,
  ]
    .filter((part) => part !== null && part !== "")
    .join(" / ");

  const isSpanned = (spanCount ?? 1) > 1;

  return (
    <div
      className={`course-block ${isSpanned ? "course-block-spanned" : "course-block-single"}`}
      style={style}
      title={title}
      {...(readOnly
        ? {}
        : {
            onMouseEnter: () => onHover(course.id),
            onMouseLeave: () => onHover(null),
          })}
    >
      {/* Top Meta Pill: Category + Period Count + Clock Time (shown on multi-period spanned blocks) */}
      {isSpanned && (
        <div className="course-block-header">
          <span
            className="course-block-badge"
            style={{
              backgroundColor: lit ? "rgba(255, 255, 255, 0.2)" : palette.badgeBg,
              color: lit ? "#ffffff" : palette.badgeText,
            }}
          >
            {categoryLabel} • {spanCount}{tx("節", "p")}
          </span>
          {timeRange && (
            <span
              className="course-block-time"
              style={{ color: lit ? "rgba(255, 255, 255, 0.9)" : "var(--studio-text-muted)" }}
            >
              {timeRange}
            </span>
          )}
        </div>
      )}

      {/* readOnly only locks edit affordances; title links stay interactive. */}
      {course.url !== null ? (
        <a
          href={course.url}
          target="_blank"
          rel="noopener noreferrer"
          className="course-block-title course-block-title-btn"
          title={tx("在學校原始頁開啟課程大綱", "Open the syllabus on the school's original page")}
          aria-label={tx(`開啟 ${name} 的學校大綱頁`, `Open the school outline page for ${name}`)}
          onClick={(event) => event.stopPropagation()}
        >
          {name}
        </a>
      ) : onViewCourse !== undefined ? (
        <button
          type="button"
          className="course-block-title course-block-title-btn"
          title={tx("檢視課程詳細資訊與大綱", "View course details and syllabus")}
          onClick={(event) => {
            event.stopPropagation();
            onViewCourse(course);
          }}
        >
          {name}
        </button>
      ) : (
        <div className="course-block-title">
          {name}
        </div>
      )}

      {/* Bottom Meta: Teacher & Classroom - only full layout for spanned blocks */}
      {isSpanned && (teacher !== "" || room !== "") && (
        <div className="course-block-meta">
          {teacher !== "" && (
            <div
              className="course-block-teacher"
              style={{ color: lit ? "rgba(255, 255, 255, 0.92)" : palette.roomText }}
            >
              <PersonFill size={10.5} className="flex-shrink-0" />
              <span>{teacher}</span>
            </div>
          )}
          {room !== "" && (
            <div
              className="course-block-room"
              style={{ color: lit ? "rgba(255, 255, 255, 0.92)" : palette.roomText }}
            >
              <GeoAltFill size={9.5} className="flex-shrink-0" />
              <span>{room}</span>
            </div>
          )}
        </div>
      )}

      {/* Delete Action */}
      {!readOnly && (
        <button
          type="button"
          className="course-block-delete"
          aria-label={tx(`移除 ${name}`, `Remove ${name}`)}
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
