/**
 * Selection state for the timetable: in-memory list + localStorage.
 *
 * Persistence contract (plan todo 10 → todo 11 seam):
 * - `nsysu_crs_selected` stores the minimal shape `[{ "courseId": "uuid" }]`
 *   in selection order. Todo 11 lifts exactly this shape into server plans.
 * - `nsysu_crs_selected_cache` stores a `{ courseId: CourseOut }` snapshot so
 *   the grid can be re-rendered after a reload without re-fetching; it is
 *   auxiliary and may be dropped any time (ids are the source of truth).
 * - Every change dispatches the `SELECTION_CHANGED_EVENT` CustomEvent on
 *   `window` with `{ courseIds: string[] }` — todo 11 subscribes to sync to
 *   server-side plans without touching this module.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";

import type { CourseOut } from "../lib/api";

export const STORAGE_KEY = "nsysu_crs_selected";
export const CACHE_KEY = "nsysu_crs_selected_cache";
export const SELECTION_CHANGED_EVENT = "nsysu-crs:selection-changed";

export interface SelectionContextValue {
  /** Selected courses in add order (re-render source of truth). */
  selected: CourseOut[];
  isSelected: (courseId: string) => boolean;
  add: (course: CourseOut) => void;
  remove: (courseId: string) => void;
  toggle: (course: CourseOut) => void;
  clear: () => void;
  /**
   * Whole-list replacement (server-plan hydration, todo 11). ``silent``
   * suppresses the SELECTION_CHANGED_EVENT so the plans sync layer does not
   * echo a hydration straight back into a PUT.
   */
  replace: (courses: CourseOut[], opts?: { silent?: boolean }) => void;
}

const SelectionContext = createContext<SelectionContextValue | null>(null);

function readIds(): string[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw === null) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    const ids: string[] = [];
    for (const entry of parsed) {
      if (
        typeof entry === "object" &&
        entry !== null &&
        "courseId" in entry &&
        typeof (entry as { courseId: unknown }).courseId === "string"
      ) {
        ids.push((entry as { courseId: string }).courseId);
      }
    }
    return ids;
  } catch {
    return [];
  }
}

function readCache(): Record<string, CourseOut> {
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    if (raw === null) return {};
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null) return {};
    return parsed as Record<string, CourseOut>;
  } catch {
    return {};
  }
}

function hydrateInitial(): CourseOut[] {
  const cache = readCache();
  const courses: CourseOut[] = [];
  for (const id of readIds()) {
    const course = cache[id];
    if (course !== undefined && course.id === id) {
      courses.push(course);
    }
  }
  return courses;
}

function persist(courses: readonly CourseOut[]): void {
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify(courses.map((c) => ({ courseId: c.id }))),
    );
    const cache: Record<string, CourseOut> = {};
    for (const course of courses) {
      cache[course.id] = course;
    }
    localStorage.setItem(CACHE_KEY, JSON.stringify(cache));
  } catch {
    // localStorage unavailable (private mode / quota): selection stays in memory.
  }
}

function dispatchChanged(courses: readonly CourseOut[]): void {
  window.dispatchEvent(
    new CustomEvent(SELECTION_CHANGED_EVENT, {
      detail: { courseIds: courses.map((c) => c.id) },
    }),
  );
}

export function SelectionProvider({ children }: { children: ReactNode }) {
  const [selected, setSelected] = useState<CourseOut[]>(hydrateInitial);
  const skipFirstEvent = useRef(true);
  const silentNext = useRef(false);

  // Persist + emit on every post-mount change (hydration itself is not a change).
  useEffect(() => {
    if (skipFirstEvent.current) {
      skipFirstEvent.current = false;
      return;
    }
    persist(selected);
    if (silentNext.current) {
      silentNext.current = false;
      return;
    }
    dispatchChanged(selected);
  }, [selected]);

  const selectedIds = useMemo(
    () => new Set(selected.map((c) => c.id)),
    [selected],
  );

  const isSelected = useCallback(
    (courseId: string) => selectedIds.has(courseId),
    [selectedIds],
  );

  const add = useCallback((course: CourseOut) => {
    setSelected((prev) =>
      prev.some((c) => c.id === course.id) ? prev : [...prev, course],
    );
  }, []);

  const remove = useCallback((courseId: string) => {
    setSelected((prev) => prev.filter((c) => c.id !== courseId));
  }, []);

  const toggle = useCallback((course: CourseOut) => {
    setSelected((prev) =>
      prev.some((c) => c.id === course.id)
        ? prev.filter((c) => c.id !== course.id)
        : [...prev, course],
    );
  }, []);

  const clear = useCallback(() => {
    setSelected([]);
  }, []);

  const replace = useCallback((courses: CourseOut[], opts?: { silent?: boolean }) => {
    if (opts?.silent === true) {
      silentNext.current = true;
    }
    setSelected(courses);
  }, []);

  const value = useMemo<SelectionContextValue>(
    () => ({ selected, isSelected, add, remove, toggle, clear, replace }),
    [selected, isSelected, add, remove, toggle, clear, replace],
  );

  return (
    <SelectionContext.Provider value={value}>
      {children}
    </SelectionContext.Provider>
  );
}

export function useSelection(): SelectionContextValue {
  const ctx = useContext(SelectionContext);
  if (ctx === null) {
    throw new Error("useSelection must be used inside SelectionProvider");
  }
  return ctx;
}
