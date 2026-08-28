import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRepeat,
  BookmarkCheck,
  CalendarWeek,
  Camera,
  Check2,
  CheckCircleFill,
  Clock,
  Mortarboard,
} from "react-bootstrap-icons";

import { ApiError, fetchSelections, syncSelections } from "../lib/api";
import type { SelectionItem } from "../lib/api";
import ScheduleTable from "../components/ScheduleTable";
import { buildSelectionGridCourses } from "../lib/selectionGrid";
import { downloadGridPng } from "../lib/export";

const STATE_ORDER = ["選上", "登記加選", "失敗"];
const STATE_BADGE: Record<string, string> = {
  選上: "bg-emerald-100 text-emerald-800 border border-emerald-300",
  登記加選: "bg-blue-100 text-blue-800 border border-blue-300",
  失敗: "bg-red-100 text-red-800 border border-red-300",
};

interface DiffCounts {
  added: number;
  removed: number;
  unchanged: number;
}

function badgeClass(state: string): string {
  return STATE_BADGE[state] ?? "text-bg-secondary";
}

function SelectionCard({ item }: { item: SelectionItem }) {
  const meta = [
    item.course_no ?? item.code ?? null,
    item.dept,
    item.credit !== null ? `${item.credit}學分` : null,
    item.compulsory_elective !== "" ? item.compulsory_elective : null,
    item.teacher,
    item.times,
    item.room ?? item.room_text,
  ]
    .filter((part) => part !== null && part !== "")
    .join(" · ");

  return (
    <div className="selection-card" data-state={item.state}>
      <div className="d-flex justify-content-between align-items-center gap-3 w-100 min-w-0">
        <div className="min-w-0 flex-grow-1">
          <div className="d-flex align-items-center gap-2 min-w-0 overflow-hidden mb-1">
            <span className="fw-bold text-dark text-truncate me-1.5" style={{ fontSize: "0.9rem" }}>
              {item.name}
            </span>
            {item.unknown && (
              <span className="badge text-bg-secondary flex-shrink-0" style={{ fontSize: "0.68rem" }}>
                目錄查無此課
              </span>
            )}
          </div>
          <div className="text-muted small text-truncate" style={{ fontSize: "0.74rem" }}>
            {meta !== "" ? meta : "無詳細開課資訊"}
          </div>
        </div>
        <span className={`badge ${badgeClass(item.state)} px-2.5 py-1 rounded-pill flex-shrink-0`} style={{ fontSize: "0.72rem" }}>
          {item.state}
        </span>
      </div>
    </div>
  );
}

function SelectedPage() {
  const [items, setItems] = useState<SelectionItem[]>([]);
  const [syncedAt, setSyncedAt] = useState<string | null>(null);
  const [diff, setDiff] = useState<DiffCounts | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exportSuccess, setExportSuccess] = useState(false);
  const [errorText, setErrorText] = useState<string | null>(null);
  const exportRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    fetchSelections()
      .then((body) => {
        if (cancelled) return;
        setItems(body.items);
        setSyncedAt(body.synced_at);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 503) {
          setErrorText("學校系統異常，稍後再試");
        } else if (!(err instanceof ApiError) || err.status !== 401) {
          setErrorText("無法讀取已選資料，請稍後再試");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const onSync = useCallback(() => {
    if (syncing) return;
    setSyncing(true);
    setErrorText(null);
    syncSelections()
      .then((body) => {
        setItems(body.items);
        setSyncedAt(body.synced_at);
        setDiff({
          added: body.added.length,
          removed: body.removed.length,
          unchanged: body.unchanged.length,
        });
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 503) {
          setErrorText("學校系統異常，稍後再試（仍顯示上次同步結果）");
        } else if (!(err instanceof ApiError) || err.status !== 401) {
          setErrorText("同步失敗，請稍後再試");
        }
      })
      .finally(() => setSyncing(false));
  }, [syncing]);

  const { courses: gridCourses, unplaced: unplacedCourses } = useMemo(
    () => buildSelectionGridCourses(items),
    [items],
  );

  const selectedCredits = useMemo(() => {
    return items
      .filter((i) => i.state === "選上" && typeof i.credit === "number")
      .reduce((sum, i) => sum + (i.credit ?? 0), 0);
  }, [items]);

  const selectedCount = useMemo(() => items.filter((i) => i.state === "選上").length, [items]);
  const registeredCount = useMemo(() => items.filter((i) => i.state === "登記加選").length, [items]);
  const failedCount = useMemo(() => items.filter((i) => i.state === "失敗").length, [items]);

  const groups = useMemo(() => {
    const res = STATE_ORDER.map((state) => ({
      state,
      rows: items.filter((item) => item.state === state),
    })).filter((group) => group.rows.length > 0);
    const extraStates = [
      ...new Set(items.map((item) => item.state)),
    ].filter((state) => !STATE_ORDER.includes(state));
    for (const state of extraStates) {
      res.push({ state, rows: items.filter((item) => item.state === state) });
    }
    return res;
  }, [items]);

  const handleExportPng = async () => {
    if (!exportRef.current || gridCourses.length === 0 || exporting) return;
    setExporting(true);
    try {
      await downloadGridPng(exportRef.current, "中山115-1已選週課表", gridCourses.length);
      setExportSuccess(true);
      setTimeout(() => setExportSuccess(false), 2500);
    } catch (err) {
      console.error("Export PNG failed:", err);
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="w-100 pb-4">
      {/* Top Header Card & Quick Sync */}
      <div className="card shadow-sm border-0 rounded-4 mb-3">
        <div className="card-body p-3.5 px-4">
          <div className="d-flex align-items-center justify-content-between flex-wrap gap-3">
            <div>
              <div className="d-flex align-items-center gap-2">
                <BookmarkCheck className="text-teal-600" size={22} />
                <h1 className="h5 fw-bold mb-0 text-dark">我的已選狀態與週課表</h1>
                <span className="badge bg-teal-50 text-teal-800 border border-teal-200" style={{ fontSize: "0.72rem" }}>
                  115-1 正式修課紀錄
                </span>
              </div>
              <div className="text-muted small mt-1 d-flex align-items-center gap-2 flex-wrap" role="status">
                <span>{syncedAt === null ? "尚未從學校系統同步資料" : `上次同步時間：${syncedAt}`}</span>
                {diff !== null && (
                  <span className="badge text-bg-light border" data-testid="sync-diff">
                    新增 {diff.added} · 移除 {diff.removed} · 未變 {diff.unchanged}
                  </span>
                )}
              </div>
            </div>

            <div className="d-flex align-items-center gap-2 flex-wrap">
              {gridCourses.length > 0 && (
                <button
                  type="button"
                  className={`btn ${exportSuccess ? "btn-success" : "btn-outline-brand"} d-inline-flex align-items-center gap-1.5 shadow-sm`}
                  onClick={() => void handleExportPng()}
                  disabled={exporting}
                  title="匯出為高解析度 PNG 課表圖片"
                  style={{ fontSize: "0.84rem", padding: "0.45rem 0.9rem" }}
                >
                  {exporting ? (
                    <span className="spinner-border spinner-border-sm" role="status" aria-hidden="true" />
                  ) : exportSuccess ? (
                    <CheckCircleFill size={14} />
                  ) : (
                    <Camera size={14} />
                  )}
                  <span>{exporting ? "產生圖片中…" : exportSuccess ? "已成功下載！" : "匯出課表圖片"}</span>
                </button>
              )}

              <button
                type="button"
                className="btn btn-brand d-inline-flex align-items-center gap-1.5 shadow-sm"
                onClick={onSync}
                disabled={syncing}
                style={{ fontSize: "0.84rem", padding: "0.45rem 0.9rem" }}
              >
                <ArrowRepeat className={syncing ? "spinner-border spinner-border-sm" : ""} size={14} />
                <span>{syncing ? "同步中…" : "同步學校系統"}</span>
              </button>
            </div>
          </div>

          {errorText !== null && (
            <div className="alert alert-warning py-2 px-3 small rounded-3 mt-3 mb-0" role="alert">
              {errorText}
            </div>
          )}

          {/* Quick Stat Summary Pills */}
          {!loading && syncedAt !== null && (
            <div className="d-flex align-items-center gap-2 flex-wrap mt-2.5 pt-2.5 border-top">
              <div className="selected-stat-chip">
                <Mortarboard className="text-teal-600" size={15} />
                <span className="text-muted small">總修習：</span>
                <strong className="text-teal-800">{selectedCredits} 學分</strong>
              </div>

              <div className="selected-stat-chip">
                <Check2 className="text-success" size={16} />
                <span className="text-muted small">正式選上：</span>
                <strong className="text-success">{selectedCount} 門課</strong>
              </div>

              <div className="selected-stat-chip">
                <Clock className="text-primary" size={14} />
                <span className="text-muted small">登記加選中：</span>
                <strong className="text-primary">{registeredCount} 門課</strong>
              </div>

              <div className="selected-stat-chip">
                <BookmarkCheck className="text-secondary" size={14} />
                <span className="text-muted small">篩選落選/失敗：</span>
                <strong className={failedCount > 0 ? "text-danger" : "text-muted"}>{failedCount} 門課</strong>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Main Studio View: Left Timetable Canvas + Right Course Status Breakdown */}
      {loading ? (
        <div className="card shadow-sm border-0 rounded-4 p-5 text-center bg-white">
          <div className="spinner-border text-teal-600 mx-auto mb-2" role="status" />
          <p className="text-muted small mb-0">正在讀取學校已選課程資料…</p>
        </div>
      ) : syncedAt === null ? (
        <div className="card shadow-sm border-0 rounded-4 p-5 text-center bg-white">
          <BookmarkCheck className="text-muted opacity-50 mx-auto mb-2" size={36} />
          <h3 className="h6 fw-bold text-dark">尚未載入已選資料</h3>
          <p className="text-muted small mb-3">請點選上方「同步學校系統」從教務處選課系統讀取最新選課狀態與週課表。</p>
          <button
            type="button"
            className="btn btn-brand d-inline-flex align-items-center gap-1.5 mx-auto shadow-sm"
            onClick={onSync}
            disabled={syncing}
          >
            <ArrowRepeat className={syncing ? "spinner-border spinner-border-sm" : ""} size={14} />
            <span>{syncing ? "同步中…" : "立即同步我的已選"}</span>
          </button>
        </div>
      ) : items.length === 0 ? (
        <div className="card shadow-sm border-0 rounded-4 p-5 text-center bg-white">
          <p className="text-muted small mb-0">學校系統目前無任何已選紀錄。</p>
        </div>
      ) : (
        <div className="row g-3">
          {/* Left Canvas: Timetable View */}
          <div className="col-12 col-xl-8">
            <div className="card shadow-sm border-0 rounded-4 h-100">
              <div className="card-body p-3.5">
                <div className="d-flex align-items-center justify-content-between flex-wrap gap-2 mb-3">
                  <div className="d-flex align-items-center gap-2">
                    <CalendarWeek className="text-teal-600" size={18} />
                    <h2 className="h6 fw-bold text-dark mb-0">
                      本學期週課表 (已選上 {gridCourses.length} 門)
                    </h2>
                  </div>
                  <span className="text-muted small" style={{ fontSize: "0.76rem" }}>
                    唯讀預覽模式 · 加退選請前往「送單中心」
                  </span>
                </div>

                <div ref={exportRef} className="schedule-export-container p-2 bg-white rounded-3">
                  <ScheduleTable
                    selectedCourses={gridCourses}
                    hoveredCourseId={null}
                    onCourseHover={() => undefined}
                    onCourseRemove={() => undefined}
                    readOnly
                  />
                </div>

                {unplacedCourses.length > 0 && (
                  <div className="alert alert-warning py-1.5 px-3 small rounded-3 mt-2 mb-0" role="alert">
                    {unplacedCourses.length} 門「選上」課程的時間資料無法解析，僅列於右側清單。
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Right Panel: Course Status List */}
          <div className="col-12 col-xl-4">
            <div className="card shadow-sm border-0 rounded-4 h-100">
              <div className="card-body p-3.5">
                <div className="d-flex align-items-center justify-content-between mb-3">
                  <h2 className="h6 fw-bold text-dark mb-0 d-flex align-items-center gap-2">
                    <BookmarkCheck className="text-teal-600" size={16} />
                    <span>各狀態修課清單</span>
                  </h2>
                  <span className="badge text-bg-light border font-monospace" style={{ fontSize: "0.72rem" }}>
                    共 {items.length} 門
                  </span>
                </div>

                <div className="d-flex flex-column gap-3.5" style={{ maxHeight: "calc(100vh - 16rem)", overflowY: "auto" }}>
                  {groups.map((group) => (
                    <section key={group.state}>
                      <div className="d-flex align-items-center justify-content-between mb-2.5 px-1">
                        <span className="fw-bold text-dark small" style={{ fontSize: "0.85rem" }}>
                          {group.state}
                        </span>
                        <span className="badge text-bg-light border rounded-pill font-monospace" style={{ fontSize: "0.7rem", padding: "0.25rem 0.55rem" }}>
                          {group.rows.length} 門
                        </span>
                      </div>
                      <div className="selection-group">
                        {group.rows.map((item, index) => (
                          <SelectionCard
                            key={`${item.state}-${item.course_no ?? item.name}-${index}`}
                            item={item}
                          />
                        ))}
                      </div>
                    </section>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default SelectedPage;

