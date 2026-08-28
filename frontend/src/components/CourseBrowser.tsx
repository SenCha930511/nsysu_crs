import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Virtuoso } from "react-virtuoso";
import {
  Check2,
  PlusLg,
  Search,
  Sliders,
  XLg,
} from "react-bootstrap-icons";

import { fetchCourses } from "../lib/api";
import type { CourseOut, CourseQuery } from "../lib/api";
import { findClashes } from "../lib/conflicts";
import { useI18n } from "../lib/i18n";
import {
  PERIOD_CODES,
  WEEKDAYS,
  formatTimeTag,
  parseDayTimeString,
} from "../config/timeslots";
import { useSelection } from "../state/selection";

const PAGE_SIZE = 50;
const SEARCH_DEBOUNCE_MS = 300;

export type PickState = "selected" | "staged" | "failed" | null;

export interface CourseBrowserProps {
  hoveredCourseId: string | null;
  onCourseHover: (courseId: string | null) => void;
  onCoursePreview?: (course: CourseOut | null) => void;
  /** Console mode: picked/clash semantics come from these, not the plan. */
  baseCourses?: readonly CourseOut[];
  /** Console mode: row picked-state override (matched against grid courses). */
  isCoursePicked?: (course: CourseOut) => boolean;
  /** Console mode: per-row state resolver (selected/staged/failed). Takes
   * precedence over isCoursePicked when provided. */
  pickState?: (course: CourseOut) => PickState;
  /** Console mode: add/remove routes here instead of the plan selection. */
  onToggleCourse?: (course: CourseOut) => void;
  /** Fires when the user wants the course's detail sheet (name click). */
  onViewCourse?: (course: CourseOut) => void;
  /** Optional top header slot (e.g. segmented tabs) */
  headerTopSlot?: React.ReactNode;
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

const CATEGORIES: { key: string }[] = [
  { key: "all" },
  { key: "compulsory" },
  { key: "elective" },
  { key: "english" },
  { key: "available" },
];

const DAY_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

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

function gradeLabel(grade: string | null, lang: "zh" | "en"): string {
  if (lang === "en") {
    switch (grade) {
      case null:
        return "";
      case "0":
        return "Any year";
      case "1": case "2": case "3": case "4":
        return `Year ${grade}`;
      default:
        return grade;
    }
  }
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
  onCoursePreview,
  baseCourses,
  isCoursePicked,
  pickState,
  onToggleCourse,
  onViewCourse,
  headerTopSlot,
}: CourseBrowserProps) {
  const { lang, tx } = useI18n();
  const { selected, isSelected, toggle } = useSelection();
  const effBase = baseCourses ?? selected;
  const effIsPicked =
    isCoursePicked ?? ((course: CourseOut) => isSelected(course.id));
  const stateOf = useCallback(
    (course: CourseOut): PickState =>
      pickState !== undefined ? pickState(course) : effIsPicked(course) ? "selected" : null,
    [pickState, effIsPicked],
  );
  const effToggle = onToggleCourse ?? toggle;

  const categoryLabel = (key: string): string => {
    switch (key) {
      case "all": return tx("全部課程", "All courses");
      case "compulsory": return tx("必修", "Required");
      case "elective": return tx("選修", "Elective");
      case "english": return tx("EMI 英語授課", "EMI (English taught)");
      case "available": return tx("尚有名額", "Seats left");
      default: return key;
    }
  };

  const [searchInput, setSearchInput] = useState("");
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [selectedCategory, setSelectedCategory] = useState("all");
  const [showAdvancedFilters, setShowAdvancedFilters] = useState(false);
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

  // Debounce free-text search
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

  // Reload on filters change
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
        if (next.weekday === "") next.period = "";
        return next;
      });
    },
    [],
  );

  const handleCategorySelect = (key: string) => {
    setSelectedCategory(key);
    if (key === "all") {
      updateFilter({ compulsory: "", english: "" });
    } else if (key === "compulsory") {
      updateFilter({ compulsory: "true", english: "" });
    } else if (key === "elective") {
      updateFilter({ compulsory: "false", english: "" });
    } else if (key === "english") {
      updateFilter({ english: "true", compulsory: "" });
    }
  };

  const resetFilters = useCallback(() => {
    setSearchInput("");
    setSelectedCategory("all");
    setFilters(EMPTY_FILTERS);
  }, []);

  const deptOptions = useMemo(
    () => [...knownDepts.current].sort(),
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
      const st = stateOf(course);
      if (st === "selected" || st === "staged") continue;
      const clashes = findClashes(course, effBase);
      if (clashes.length > 0) {
        const detail = clashes
          .map(
            (c) =>
              `「${courseName(c.course)}」（${c.slotTags.join(" ")}）`,
          )
          .join("、");
        map.set(course.id, tx(`與已選 ${detail} 衝堂`, `Clashes with ${detail} on your timetable`));
      }
    }
    return map;
  }, [items, effBase, stateOf, tx]);

  const renderRow = useCallback(
    (_index: number, course: CourseOut) => {
      const st = stateOf(course);
      const picked = st === "selected" || st === "staged";
      const hovered = hoveredCourseId === course.id;
      const clashTip = clashByCourse.get(course.id);
      const { tags, invalid } = timeTags(course);
      const remaining = course.remaining;
      const full = remaining !== null && remaining <= 0;

      const metaParts = [
        course.dept,
        gradeLabel(course.grade, lang),
        course.class_,
        course.teacher,
      ].filter((part) => part !== null && part !== "");

      return (
        <div
          className={`studio-course-card ${picked ? "is-selected" : ""} ${
            clashTip !== undefined && !picked ? "is-conflict" : ""
          } ${hovered ? "is-hovered" : ""}`}
          data-course-id={course.id}
          title={
            picked
              ? undefined
              : (clashTip ??
                (st === "failed"
                  ? tx("上次送出失敗——點擊可再暫存重試", "Last submit failed — click to stage and retry")
                  : undefined))
          }
          onMouseEnter={() => {
            onCourseHover(course.id);
            if (onCoursePreview && !picked) {
              onCoursePreview(course);
            }
          }}
          onMouseLeave={() => {
            onCourseHover(null);
            if (onCoursePreview) {
              onCoursePreview(null);
            }
          }}
        >
          {/* Row 1: Title, Badges & Quota Pill */}
          <div className="d-flex align-items-center justify-content-between gap-2 min-w-0">
            <div className="d-flex align-items-center gap-2 min-w-0 flex-grow-1 overflow-hidden">
              {onViewCourse !== undefined ? (
                <button
                  type="button"
                  className="card-course-name btn btn-link p-0 border-0 text-truncate me-1 text-start text-decoration-none"
                  style={{ fontSize: "inherit", color: "inherit" }}
                  title={tx("查看課程詳細資訊與大綱", "View course detail & syllabus")}
                  aria-label={tx(`查看 ${courseName(course)} 詳細資訊`, `View detail of ${courseName(course)}`)}
                  onClick={(e) => {
                    e.stopPropagation();
                    onViewCourse(course);
                  }}
                >
                  {courseName(course)}
                </button>
              ) : (
                <span className="card-course-name text-truncate me-1">{courseName(course)}</span>
              )}
              {course.dept && (
                <span className="card-course-dept flex-shrink-0">{course.dept}</span>
              )}
              {course.credit !== null && (
                <span className="badge bg-teal-50 text-teal-800 border border-teal-200 flex-shrink-0" style={{ fontSize: "0.68rem" }}>
                  {lang === "en" ? `${course.credit} cr` : `${course.credit}學分`}
                </span>
              )}
              <span
                className={`badge flex-shrink-0 ${
                  course.compulsory ? "badge-compulsory" : "badge-elective"
                }`}
                style={{ fontSize: "0.68rem" }}
              >
                {course.compulsory ? tx("必修", "Required") : tx("選修", "Elective")}
              </span>
              {course.english && (
                <span className="badge badge-emi flex-shrink-0" style={{ fontSize: "0.65rem" }}>EMI</span>
              )}
            </div>

            <div className="card-quota-bar-wrapper flex-shrink-0">
              <span className={`quota-status-pill ${full ? "quota-status-full" : "quota-status-available"}`}>
                {full ? tx("額滿", "Full") : tx(`餘 ${num(remaining)}`, `${num(remaining)} left`)}
              </span>
              <span className="text-muted font-monospace d-none d-sm-inline" style={{ fontSize: "0.68rem" }}>
                ({num(course.select_n)}/{num(course.restrict)})
              </span>
            </div>
          </div>

          {/* Row 2: Teacher, Class, Room & English Title */}
          <div className="card-meta-line text-truncate">
            {metaParts.length > 0 ? metaParts.join(" · ") : tx("無詳細開課資訊", "No details available")}
            {course.name_en && (
              <span className="text-muted ms-1 text-truncate opacity-75">· {course.name_en}</span>
            )}
          </div>

          {/* Row 3: Time Badges & Add Button */}
          <div className="d-flex align-items-center justify-content-between gap-2 min-w-0 pt-0.5">
            <div className="card-time-badges min-w-0 overflow-hidden text-nowrap flex-grow-1">
              {tags.map((tag) => (
                <span key={tag} className="card-time-tag">
                  {tag}
                </span>
              ))}
              {tags.length === 0 && !invalid && (
                <span className="text-muted small" style={{ fontSize: "0.72rem" }}>{tx("無固定時段", "No fixed time")}</span>
              )}
              {invalid && (
                <span className="badge text-bg-danger" style={{ fontSize: "0.68rem" }}>{tx("時間異常", "Bad time data")}</span>
              )}
            </div>

            <button
              type="button"
              className={`btn btn-card-toggle flex-shrink-0 ${
                st === "selected"
                  ? "btn-danger shadow-sm"
                  : st === "staged"
                    ? "btn-warning shadow-sm"
                    : st === "failed"
                      ? "btn-outline-danger"
                      : "btn-brand shadow-sm"
              }`}
              data-action={picked || st === "failed" ? "remove" : "add"}
              onClick={(e) => {
                e.stopPropagation();
                effToggle(course);
              }}
            >
              {st === "selected" ? (
                <Check2 size={13} />
              ) : st === "failed" ? (
                <XLg size={13} />
              ) : (
                <PlusLg size={11} />
              )}
              <span>
                {st === "selected"
                  ? tx("已在課表", "On timetable")
                  : st === "staged"
                    ? tx("準備加選", "Staged")
                    : st === "failed"
                      ? tx("送出失敗", "Submit failed")
                      : tx("加入課表", "Add")}
              </span>
            </button>
          </div>
        </div>
      );
    },
    [stateOf, effToggle, hoveredCourseId, clashByCourse, onCourseHover, onCoursePreview, onViewCourse, lang, tx],
  );

  const ListFooter = useCallback(
    () => (
      <div className="py-3 text-center text-muted small">
        {loading
          ? tx("正在探索課程中…", "Loading courses…")
          : total === 0
            ? tx("查無符合的課程條件", "No courses match these filters")
            : items.length < total
              ? tx(`已載入 ${items.length} / ${total} 門課程`, `${items.length} / ${total} courses loaded`)
              : tx(`已載入全部 ${total} 門課程`, `All ${total} courses loaded`)}
      </div>
    ),
    [loading, items.length, total, tx],
  );

  return (
    <section className="course-discovery-pane" aria-label={tx("課程探索中心", "Course discovery")}>
      {/* Header & Search */}
      <div className="discovery-search-header">
        {headerTopSlot && (
          <div className="discovery-header-top-slot pb-2">{headerTopSlot}</div>
        )}
        <div className="studio-search-bar">
          <Search className="studio-search-icon" />
          <input
            type="search"
            className="studio-search-input"
            placeholder={tx("搜尋課名、教師姓名或關鍵字…", "Search by title, teacher, or keyword…")}
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            aria-label={tx("搜尋課程", "Search courses")}
          />
          {searchInput && (
            <button
              type="button"
              className="studio-search-clear"
              onClick={() => setSearchInput("")}
              aria-label={tx("清除搜尋", "Clear search")}
            >
              <XLg size={12} />
            </button>
          )}
        </div>

        {/* Category Pill Rail */}
        <div className="d-flex align-items-center justify-content-between gap-2">
          <div className="category-pill-rail flex-grow-1">
            {CATEGORIES.map((cat) => (
              <button
                key={cat.key}
                type="button"
                className={`category-chip ${selectedCategory === cat.key ? "active" : ""}`}
                onClick={() => handleCategorySelect(cat.key)}
              >
                {categoryLabel(cat.key)}
              </button>
            ))}
          </div>
          
          <button
            type="button"
            className={`btn btn-sm ${showAdvancedFilters ? "btn-teal-700 bg-teal-50" : "btn-light border"} p-1 px-2 d-inline-flex align-items-center gap-1 rounded-pill`}
            style={{ fontSize: "0.74rem" }}
            onClick={() => setShowAdvancedFilters(!showAdvancedFilters)}
            title={tx("更多進階篩選", "More advanced filters")}
          >
            <Sliders size={12} />
            <span>{tx("進階篩選", "Filters")}</span>
          </button>
        </div>

        {/* Advanced Filters Expandable Drawer */}
        {showAdvancedFilters && (
          <div className="secondary-filter-row mt-2 pt-2 border-top">
            <select
              className="compact-filter-select"
              value={filters.weekday}
              onChange={(e) => updateFilter({ weekday: e.target.value })}
              aria-label={tx("星期", "Weekday")}
            >
              <option value="">{tx("星期（全部）", "Weekday (all)")}</option>
              {WEEKDAYS.map((day) => (
                <option key={day.apiWeekday} value={String(day.apiWeekday)}>
                  {lang === "en" ? DAY_EN[day.index] ?? day.label : `週${day.label}`}
                </option>
              ))}
            </select>

            <select
              className="compact-filter-select"
              value={filters.period}
              onChange={(e) => updateFilter({ period: e.target.value })}
              disabled={filters.weekday === ""}
              aria-label={tx("節次", "Period")}
            >
              <option value="">{tx("節次（全部）", "Period (all)")}</option>
              {PERIOD_CODES.map((code) => (
                <option key={code} value={code}>
                  {tx(`第 ${code} 節`, `Period ${code}`)}
                </option>
              ))}
            </select>

            <select
              className="compact-filter-select"
              value={filters.grade}
              onChange={(e) => updateFilter({ grade: e.target.value })}
              aria-label={tx("年級", "Year level")}
            >
              <option value="">{tx("年級（全部）", "Year (all)")}</option>
              <option value="0">{tx("不分年級", "Any year")}</option>
              <option value="1">{tx("大一", "Year 1")}</option>
              <option value="2">{tx("大二", "Year 2")}</option>
              <option value="3">{tx("大三", "Year 3")}</option>
              <option value="4">{tx("大四", "Year 4")}</option>
            </select>

            <select
              className="compact-filter-select"
              value={filters.credit}
              onChange={(e) => updateFilter({ credit: e.target.value })}
              aria-label={tx("學分", "Credits")}
            >
              <option value="">{tx("學分（全部）", "Credits (all)")}</option>
              {creditOptions.map((credit) => (
                <option key={credit} value={String(credit)}>
                  {lang === "en" ? `${credit} cr` : `${credit} 學分`}
                </option>
              ))}
            </select>

            <input
              type="text"
              className="compact-filter-select"
              style={{ width: "110px" }}
              placeholder={tx("系所搜尋…", "Dept…")}
              list="dept-options"
              value={filters.dept}
              onChange={(e) => updateFilter({ dept: e.target.value.trim() })}
              aria-label={tx("系所", "Department")}
            />
            <datalist id="dept-options">
              {deptOptions.map((dept) => (
                <option key={dept} value={dept} />
              ))}
            </datalist>

            <button
              type="button"
              className="btn btn-sm btn-link text-secondary p-0 ms-auto text-decoration-none"
              style={{ fontSize: "0.75rem" }}
              onClick={resetFilters}
            >
              {tx("重設條件", "Reset")}
            </button>
          </div>
        )}
      </div>

      {error !== null && (
        <div className="alert alert-danger d-flex justify-content-between align-items-center py-2 mx-3 my-2 rounded-3" role="alert">
          <span className="small">{tx("課程查詢失敗：", "Course query failed: ")}{error}</span>
          <button
            type="button"
            className="btn btn-sm btn-outline-danger"
            onClick={() => loadPage(filters, 1, false)}
          >
            {tx("重試", "Retry")}
          </button>
        </div>
      )}

      {/* Virtuoso Virtualized Course List */}
      <Virtuoso
        className="discovery-virtuoso-list"
        data={items}
        endReached={endReached}
        increaseViewportBy={300}
        itemContent={renderRow}
        components={{ Footer: ListFooter }}
      />
    </section>
  );
}
