/**
 * Course browser: search box + multi-filters hitting GET /api/courses,
 * rendered as a virtualized infinite list (react-virtuoso, 50/page).
 *
 * Row layout and badge vocabulary follow the NSYSUSelectorHelper list rows
 * (MIT, https://github.com/NSYSU-OpenDev/NSYSUSelectorHelper): name, teacher
 * and dept meta, compulsory/credit/EMI badges, compact time tags ("三56"),
 * and the restrict/select/selected/remaining quota block. Conflict checking
 * against the current selection reuses our lib/conflicts.ts (same per-day
 * char-set rule as upstream's SelectorSetting.detectTimeConflict).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Virtuoso } from "react-virtuoso";
import { Check2, PlusLg, Search } from "react-bootstrap-icons";

import { fetchCourses } from "../lib/api";
import type { CourseOut, CourseQuery } from "../lib/api";
import { findClashes } from "../lib/conflicts";
import {
  PERIOD_CODES,
  WEEKDAYS,
  formatTimeTag,
  parseDayTimeString,
} from "../config/timeslots";
import { useSelection } from "../state/selection";

const PAGE_SIZE = 50; // server-fixed (plan todo 7)
const SEARCH_DEBOUNCE_MS = 300;

export interface CourseBrowserProps {
  hoveredCourseId: string | null;
  onCourseHover: (courseId: string | null) => void;
}

interface Filters {
  q: string;
  dept: string;
  grade: string; // "" | "0".."4"
  credit: string; // "" | number as string
  compulsory: string; // "" | "true" | "false"
  english: string; // "" | "true" | "false"
  weekday: string; // "" | "1".."7"
  period: string; // "" | period code (requires weekday)
}

const EMPTY_FILTERS: Filters = {
  q: "",
  dept: "",
  grade: "",
  credit: "",
  compulsory: "",
  english: "",
  weekday: "",
  period: "",
};

function filtersToQuery(filters: Filters, page: number): CourseQuery {
  const query: CourseQuery = { page };
  if (filters.q !== "") query.q = filters.q;
  if (filters.dept !== "") query.dept = filters.dept;
  if (filters.grade !== "") query.grade = filters.grade;
  if (filters.credit !== "") query.credit = Number(filters.credit);
  if (filters.compulsory !== "") {
    query.compulsory = filters.compulsory === "true";
  }
  if (filters.english !== "") query.english = filters.english === "true";
  if (filters.weekday !== "") query.weekday = Number(filters.weekday);
  if (filters.weekday !== "" && filters.period !== "") {
    query.period = filters.period;
  }
  return query;
}

function gradeLabel(grade: string | null): string {
  switch (grade) {
    case null:
      return "";
    case "0":
      return "不分年級";
    case "1":
    case "2":
    case "3":
    case "4":
      return `大${["一", "二", "三", "四"][Number(grade) - 1] ?? grade}`;
    default:
      return grade;
  }
}

function creditBadgeClass(credit: number | null): string {
  if (credit === null) return "text-bg-light border";
  if (credit <= 0) return "text-bg-secondary";
  if (credit === 1) return "text-bg-info";
  if (credit === 2) return "text-bg-primary";
  if (credit === 3) return "text-bg-success";
  return "text-bg-warning";
}

function timeTags(course: CourseOut): { tags: string[]; invalid: boolean } {
  const time = course.class_time ?? [];
  const tags: string[] = [];
  let invalid = false;
  WEEKDAYS.forEach((day) => {
    const raw = time[day.index] ?? "";
    if (raw === "") return;
    try {
      parseDayTimeString(raw);
      tags.push(formatTimeTag(day.index, raw));
    } catch {
      invalid = true;
    }
  });
  return { tags, invalid };
}

function courseName(course: CourseOut): string {
  return course.name_zh ?? course.name_en ?? course.id;
}

function num(value: number | null): string {
  return value === null ? "–" : String(value);
}

export default function CourseBrowser({
  hoveredCourseId,
  onCourseHover,
}: CourseBrowserProps) {
  const { selected, isSelected, toggle } = useSelection();

  const [searchInput, setSearchInput] = useState("");
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [items, setItems] = useState<CourseOut[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const requestSeq = useRef(0);
  const knownDepts = useRef(new Set<string>());
  const knownCredits = useRef(new Set<number>());
  const [optionVersion, setOptionVersion] = useState(0);

  const loadPage = useCallback(
    (filt: Filters, page: number, append: boolean) => {
      const seq = ++requestSeq.current;
      setLoading(true);
      setError(null);
      fetchCourses(filtersToQuery(filt, page))
        .then((data) => {
          if (seq !== requestSeq.current) return;
          let optionsChanged = false;
          for (const course of data.items) {
            if (course.dept !== null && !knownDepts.current.has(course.dept)) {
              knownDepts.current.add(course.dept);
              optionsChanged = true;
            }
            if (
              course.credit !== null &&
              !knownCredits.current.has(course.credit)
            ) {
              knownCredits.current.add(course.credit);
              optionsChanged = true;
            }
          }
          if (optionsChanged) {
            setOptionVersion((v) => v + 1);
          }
          setTotal(data.total);
          setItems((prev) => (append ? [...prev, ...data.items] : data.items));
        })
        .catch((err: unknown) => {
          if (seq !== requestSeq.current) return;
          console.error("course query failed:", err);
          setError(err instanceof Error ? err.message : String(err));
          if (!append) {
            setItems([]);
            setTotal(0);
          }
        })
        .finally(() => {
          if (seq === requestSeq.current) setLoading(false);
        });
    },
    [],
  );

  // Debounce the free-text search box into the filter state.
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setFilters((prev) =>
        prev.q === searchInput.trim()
          ? prev
          : { ...prev, q: searchInput.trim() },
      );
    }, SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  // Reload from page 1 whenever the committed filters change.
  useEffect(() => {
    loadPage(filters, 1, false);
  }, [filters, loadPage]);

  const endReached = useCallback(() => {
    if (loading) return;
    if (items.length >= total) return;
    const nextPage = Math.floor(items.length / PAGE_SIZE) + 1;
    loadPage(filters, nextPage, true);
  }, [items.length, total, loading, filters, loadPage]);

  const updateFilter = useCallback(
    (patch: Partial<Filters>) => {
      setFilters((prev) => {
        const next = { ...prev, ...patch };
        // The API rejects period without weekday: clearing the day also
        // clears the period so the two selects never drift apart.
        if (next.weekday === "") next.period = "";
        return next;
      });
    },
    [],
  );

  const resetFilters = useCallback(() => {
    setSearchInput("");
    setFilters(EMPTY_FILTERS);
  }, []);

  const deptOptions = useMemo(
    () => [...knownDepts.current].sort(),
    // optionVersion bumps whenever a fetched page contributes a new option.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [optionVersion],
  );
  const creditOptions = useMemo(
    () => [...knownCredits.current].sort((a, b) => a - b),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [optionVersion],
  );

  const clashByCourse = useMemo(() => {
    const map = new Map<string, string>();
    for (const course of items) {
      if (isSelected(course.id)) continue;
      const clashes = findClashes(course, selected);
      if (clashes.length > 0) {
        const detail = clashes
          .map(
            (c) =>
              `「${courseName(c.course)}」（${c.slotTags.join(" ")}）`,
          )
          .join("、");
        map.set(course.id, `與已選 ${detail} 衝堂`);
      }
    }
    return map;
  }, [items, selected, isSelected]);

  const renderRow = useCallback(
    (_index: number, course: CourseOut) => {
      const picked = isSelected(course.id);
      const hovered = hoveredCourseId === course.id;
      const clashTip = clashByCourse.get(course.id);
      const { tags, invalid } = timeTags(course);
      const remaining = course.remaining;
      const full = remaining !== null && remaining <= 0;

      const metaParts = [
        course.dept,
        gradeLabel(course.grade),
        course.class_,
        course.teacher,
      ].filter((part) => part !== null && part !== "");

      const rowClass = [
        "course-row",
        picked ? "course-row-selected" : "",
        clashTip !== undefined && !picked ? "course-row-conflict" : "",
        hovered ? "course-row-hovered" : "",
      ]
        .filter((cls) => cls !== "")
        .join(" ");

      return (
        <div
          className={rowClass}
          data-course-id={course.id}
          title={picked ? undefined : clashTip}
          onMouseEnter={() => onCourseHover(course.id)}
          onMouseLeave={() => onCourseHover(null)}
        >
          <div className="d-flex justify-content-between gap-2">
            <div className="course-row-main">
              <div className="d-flex align-items-baseline gap-2 flex-wrap">
                <span className="fw-semibold">{courseName(course)}</span>
                {course.name_en !== null && course.name_en !== "" && (
                  <span className="text-muted small">{course.name_en}</span>
                )}
              </div>
              {metaParts.length > 0 && (
                <div className="text-muted small">{metaParts.join(" · ")}</div>
              )}
              {invalid && (
                <span className="badge text-bg-danger me-1">時間資料異常</span>
              )}
              <div className="course-row-tags">
                {tags.map((tag) => (
                  <span key={tag} className="time-tag">
                    {tag}
                  </span>
                ))}
                {tags.length === 0 && !invalid && (
                  <span className="text-muted small">無固定上課時間</span>
                )}
              </div>
            </div>
            <div className="course-row-side text-end">
              <div className="mb-1">
                <span
                  className={`badge me-1 ${
                    course.compulsory
                      ? "text-bg-danger"
                      : "text-bg-light border"
                  }`}
                >
                  {course.compulsory ? "必修" : "選修"}
                </span>
                <span className={`badge me-1 ${creditBadgeClass(course.credit)}`}>
                  {course.credit === null ? "學分–" : `${course.credit} 學分`}
                </span>
                {course.english && (
                  <span className="badge text-bg-dark me-1">EMI</span>
                )}
              </div>
              <div className="quota-badges mb-1" aria-label="名額">
                <span className="badge text-bg-secondary" title="人數上限">
                  限 {num(course.restrict)}
                </span>
                <span className="badge text-bg-info" title="登記人數">
                  登 {num(course.select_n)}
                </span>
                <span className="badge text-bg-primary" title="已選上人數">
                  上 {num(course.selected_n)}
                </span>
                <span
                  className={`badge ${full ? "text-bg-danger" : "text-bg-success"}`}
                  title="剩餘名額"
                >
                  {full ? "額滿" : `餘 ${num(remaining)}`}
                </span>
              </div>
              <button
                type="button"
                className={`btn btn-sm ${
                  picked ? "btn-danger" : "btn-outline-primary"
                }`}
                data-action={picked ? "remove" : "add"}
                onClick={() => toggle(course)}
              >
                {picked ? <Check2 /> : <PlusLg />} {picked ? "已加入" : "加入"}
              </button>
            </div>
          </div>
        </div>
      );
    },
    [isSelected, hoveredCourseId, clashByCourse, onCourseHover, toggle],
  );

  const ListFooter = useCallback(
    () => (
      <div className="py-3 text-center text-muted small">
        {loading
          ? "載入中…"
          : total === 0
            ? "查無符合的課程"
            : items.length < total
              ? `已載入 ${items.length} / ${total} 門`
              : `全部 ${total} 門已載入`}
      </div>
    ),
    [loading, items.length, total],
  );

  return (
    <section className="course-browser" aria-label="課程搜尋">
      <div className="filter-bar">
        <div className="row g-2 align-items-center">
          <div className="col-12 col-xl-5">
            <div className="input-group input-group-sm">
              <span className="input-group-text">
                <Search />
              </span>
              <input
                type="search"
                className="form-control"
                placeholder="搜尋課名 / 教師…"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                aria-label="搜尋課程"
              />
            </div>
          </div>
          <div className="col-6 col-sm-4 col-xl-2">
            <select
              className="form-select form-select-sm"
              value={filters.weekday}
              onChange={(e) => updateFilter({ weekday: e.target.value })}
              aria-label="星期"
            >
              <option value="">星期（全部）</option>
              {WEEKDAYS.map((day) => (
                <option key={day.apiWeekday} value={String(day.apiWeekday)}>
                  星期{day.label}
                </option>
              ))}
            </select>
          </div>
          <div className="col-6 col-sm-4 col-xl-2">
            <select
              className="form-select form-select-sm"
              value={filters.period}
              onChange={(e) => updateFilter({ period: e.target.value })}
              disabled={filters.weekday === ""}
              aria-label="節次"
            >
              <option value="">節次（全部）</option>
              {PERIOD_CODES.map((code) => (
                <option key={code} value={code}>
                  第 {code} 節
                </option>
              ))}
            </select>
          </div>
          <div className="col-6 col-sm-4 col-xl-3">
            <input
              type="text"
              className="form-control form-control-sm"
              placeholder="系所（如 資工系）"
              list="dept-options"
              value={filters.dept}
              onChange={(e) => updateFilter({ dept: e.target.value.trim() })}
              aria-label="系所"
            />
            <datalist id="dept-options">
              {deptOptions.map((dept) => (
                <option key={dept} value={dept} />
              ))}
            </datalist>
          </div>
        </div>
        <div className="row g-2 align-items-center mt-0">
          <div className="col-6 col-sm-3 col-xl-2">
            <select
              className="form-select form-select-sm"
              value={filters.grade}
              onChange={(e) => updateFilter({ grade: e.target.value })}
              aria-label="年級"
            >
              <option value="">年級（全部）</option>
              <option value="0">不分年級</option>
              <option value="1">大一</option>
              <option value="2">大二</option>
              <option value="3">大三</option>
              <option value="4">大四</option>
            </select>
          </div>
          <div className="col-6 col-sm-3 col-xl-2">
            <select
              className="form-select form-select-sm"
              value={filters.credit}
              onChange={(e) => updateFilter({ credit: e.target.value })}
              aria-label="學分"
            >
              <option value="">學分（全部）</option>
              {creditOptions.map((credit) => (
                <option key={credit} value={String(credit)}>
                  {credit} 學分
                </option>
              ))}
            </select>
          </div>
          <div className="col-6 col-sm-3 col-xl-2">
            <select
              className="form-select form-select-sm"
              value={filters.compulsory}
              onChange={(e) => updateFilter({ compulsory: e.target.value })}
              aria-label="必選修"
            >
              <option value="">必選修（全部）</option>
              <option value="true">必修</option>
              <option value="false">選修</option>
            </select>
          </div>
          <div className="col-6 col-sm-3 col-xl-2">
            <select
              className="form-select form-select-sm"
              value={filters.english}
              onChange={(e) => updateFilter({ english: e.target.value })}
              aria-label="英語授課"
            >
              <option value="">語言（全部）</option>
              <option value="true">英語授課</option>
              <option value="false">非英語授課</option>
            </select>
          </div>
          <div className="col-12 col-xl-4 d-flex justify-content-xl-end align-items-center gap-2">
            <span className="text-muted small" aria-live="polite">
              共 {total} 門
            </span>
            <button
              type="button"
              className="btn btn-sm btn-outline-secondary"
              onClick={resetFilters}
            >
              清除條件
            </button>
          </div>
        </div>
      </div>

      {error !== null && (
        <div className="alert alert-danger d-flex justify-content-between align-items-center py-2" role="alert">
          <span>課程查詢失敗:{error}</span>
          <button
            type="button"
            className="btn btn-sm btn-outline-danger"
            onClick={() => loadPage(filters, 1, false)}
          >
            重試
          </button>
        </div>
      )}

      <Virtuoso
        className="course-list-virtuoso"
        data={items}
        endReached={endReached}
        increaseViewportBy={300}
        itemContent={renderRow}
        components={{ Footer: ListFooter }}
      />
    </section>
  );
}
