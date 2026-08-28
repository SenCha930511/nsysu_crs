/**
 * One course block inside a timetable grid cell.
 *
 * Adapted from NSYSU-OpenDev/NSYSUSelectorHelper (MIT License,
 * Copyright (c) Cellery Lin and whats2000):
 *   client-website/src/components/ScheduleTable/CourseBlock.tsx
 *   https://github.com/NSYSU-OpenDev/NSYSUSelectorHelper
 *
 * Behavior kept from upstream: bold name + room lines, deterministic light
 * hash-color per course, hover swaps to the brand color with a glow, delete
 * button appears on hover. Deviation: upstream hashes the leading-alpha
 * prefix of the school course number (so same-dept courses share a color;
 * Number is a school course code in their data). Our id is a UUID, so we
 * hash the full id+name instead — still deterministic per course, and the
 * light brightness mask is unchanged.
 */

import { Trash3 } from "react-bootstrap-icons";

import type { CourseOut } from "../lib/api";

export function hashLightColor(input: string): string {
  let hash = 0;
  for (let i = 0; i < input.length; i++) {
    hash = input.charCodeAt(i) + ((hash << 5) - hash);
  }
  // Brightness mask keeps the color in the light half of the RGB range; the
  // result is always in [0x808080, 0xffffff], i.e. exactly 6 hex digits.
  const color = (hash & 0x7f7f7f) + 0x808080;
  return `#${color.toString(16).padStart(6, "0")}`;
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

  const lit = hovered && !readOnly;
  const style = {
    backgroundColor: lit
      ? "var(--crs-brand)"
      : hashLightColor(course.id + (course.name_zh ?? "")),
    color: lit ? "#fff" : "initial",
    boxShadow: lit ? "0 0 0 0.25rem var(--crs-brand-glow)" : "none",
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
      <span className="d-block fw-bold">{name}</span>
      {roomLines.map((room, index) => (
        <span key={`room-${index}`} className="d-block">
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
