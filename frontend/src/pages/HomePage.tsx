/**
 * Unified console (~/): the merged face of browse + selections + write.
 * LEFT  = your real timetable (synced school selections) + staged adds and
 *         marked drops, with the send bar layered under the canvas.
 * RIGHT = two tabs: 查課 (full catalog browse, click stages add/drop) and
 *         已選 (synced selections + per-row undoable drop marks).
 * SEND  = stage-gated preview -> verdict modal (quota + re-password) ->
 *         submit -> live job polling -> auto re-sync of selections.
 * Identity law (live-probed today): ops speak 課別代號 only.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRepeat,
  BookmarkCheck,
  CalendarCheck,
  CheckCircleFill,
  Download,
  Eraser,
  ExclamationTriangleFill,
  HourglassSplit,
  Search,
  Send,
  XCircleFill,
} from "react-bootstrap-icons";
import { Link } from "react-router-dom";

import CourseBrowser from "../components/CourseBrowser";
import CourseDetailModal from "../components/CourseDetailModal";
import ScheduleTable from "../components/ScheduleTable";
import {
  ApiError,
  fetchSelections,
  fetchStage,
  fetchWriteJob,
  previewWrite,
  submitWrite,
  syncSelections,
} from "../lib/api";
import type {
  CourseOut,
  JobView,
  PreviewResponse,
  SelectionItem,
  StageInfo,
} from "../lib/api";
import {
  mergeGridCourses,
  selectionGridKey,
  selectionShortCode,
  toWriteOps,
} from "../lib/consoleOps";
import type { StagedAdd } from "../lib/consoleOps";
import { downloadGridPng } from "../lib/export";
import { useI18n } from "../lib/i18n";
import { buildSelectionGridCourses } from "../lib/selectionGrid";
import { totalCreditsAndHours } from "../lib/totals";
import { outcomeCopy } from "../lib/writeOps";
import { useAuth } from "../state/auth";

type Tab = "browse" | "selections";
type SendPhase = "idle" | "previewing" | "confirm" | "job";

const POLL_MS = 1500;
const JOB_TERMINAL = new Set(["done", "failed", "cancelled", "session_superseded"]);

function shortName(course: CourseOut | SelectionItem): string {
  return "name" in course ? course.name : (course.name_zh ?? course.name_en ?? course.id);
}

function formatSyncedTime(isoStr: string | null): string {
  if (!isoStr) return "";
  try {
    const d = new Date(isoStr);
    if (isNaN(d.getTime())) {
      const timePart = isoStr.split("T")[1]?.split("+")[0]?.split(".")[0];
      return timePart || isoStr;
    }
    return d.toLocaleTimeString("zh-TW", { hour12: false });
  } catch {
    return isoStr;
  }
}

function HomePage() {
  const { lang, tx } = useI18n();
  const { status, csrfToken } = useAuth();
  const authed = status === "authed" && csrfToken !== null;

  // ---- real selections (school truth) ----
  const [items, setItems] = useState<SelectionItem[]>([]);
  const [syncedAt, setSyncedAt] = useState<string | null>(null);
  const [loading, setLoading] = useState(authed);
  const [syncing, setSyncing] = useState(false);
  const [syncError, setSyncError] = useState<string | null>(null);

  // ---- staging ----
  const [stagedAdds, setStagedAdds] = useState<StagedAdd[]>([]);
  const [stagedDrops, setStagedDrops] = useState<SelectionItem[]>([]);
  const [failedAdds, setFailedAdds] = useState<CourseOut[]>([]);
  const [failedCodes, setFailedCodes] = useState<Set<string>>(new Set());

  // ---- tabs / browse ----
  const [tab, setTab] = useState<Tab>("browse");
  const [hoveredCourseId, setHoveredCourseId] = useState<string | null>(null);
  const [previewCourse, setPreviewCourse] = useState<CourseOut | null>(null);
  const [detailCourse, setDetailCourse] = useState<CourseOut | null>(null);

  // ---- png (parity with the previous home) ----
  const gridRef = useRef<HTMLDivElement>(null);
  const [pngState, setPngState] = useState<"idle" | "busy">("idle");
  const [pngError, setPngError] = useState<string | null>(null);

  // ---- stage + send flow ----
  const [stage, setStage] = useState<StageInfo | null>(null);
  const [phase, setPhase] = useState<SendPhase>("idle");
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [sendError, setSendError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [job, setJob] = useState<JobView | null>(null);
  const [jobNote, setJobNote] = useState<string | null>(null);
  const [reconcileNote, setReconcileNote] = useState<string | null>(null);

  // ---- loaders ----
  const loadSelections = useCallback(() => {
    if (!authed) { setLoading(false); return; }
    fetchSelections()
      .then((body) => {
        setItems(body.items);
        setSyncedAt(body.synced_at);
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 503) {
          setSyncError(tx("學校系統異常，稍後再試", "The school system is unavailable right now"));
        } else if (!(err instanceof ApiError) || err.status !== 401) {
          setSyncError(tx("無法讀取已選資料，請稍後再試", "Couldn't load your selections. Please try again shortly"));
        }
      })
      .finally(() => setLoading(false));
  }, [authed, tx]);

  useEffect(() => { loadSelections(); }, [loadSelections]);

  useEffect(() => {
    if (!authed) return;
    fetchStage()
      .then((info) => setStage(info))
      .catch((err: unknown) => {
        if (!(err instanceof ApiError) || err.status !== 401) {
          setStage(null);
        }
      });
  }, [authed]);

  const onSync = useCallback(() => {
    if (syncing || !authed) return;
    setSyncing(true);
    setSyncError(null);
    syncSelections()
      .then((body) => {
        setItems(body.items);
        setSyncedAt(body.synced_at);
        setReconcileNote(
          lang === "en"
            ? `Reconciled: +${body.added.length} added · −${body.removed.length} removed · ${body.unchanged.length} unchanged`
            : `對帳完成：新增 ${body.added.length} · 移除 ${body.removed.length} · 未變 ${body.unchanged.length}`,
        );
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 503) {
          setSyncError(tx(
            "學校系統異常，稍後再試（仍顯示上次同步結果）",
            "The school system is unavailable right now (showing your last sync)",
          ));
        } else if (!(err instanceof ApiError) || err.status !== 401) {
          setSyncError(tx("同步失敗，請稍後再試", "Sync failed. Please try again shortly"));
        }
      })
      .finally(() => setSyncing(false));
  }, [syncing, authed, lang, tx]);

  // Auto-load on fresh login: when authed and no snapshot exists yet (fresh
  // session => synced_at is null), pull the school truth once automatically.
  // The ref blocks the React-strict-mode double-effect and repeat mounts.
  const autoSyncedRef = useRef(false);
  useEffect(() => {
    if (!authed || loading || syncing || autoSyncedRef.current || syncedAt !== null) {
      return;
    }
    autoSyncedRef.current = true;
    onSync();
  }, [authed, loading, syncing, syncedAt, onSync]);

  // ---- grid derivation ----
  const { courses: selectedCourses, unplaced } = useMemo(
    () => buildSelectionGridCourses(items),
    [items],
  );
  const selectedShorts = useMemo(
    () =>
      new Set(
        items
          .map(selectionShortCode)
          .filter((v): v is string => v !== null),
      ),
    [items],
  );
  const dropKeys = useMemo(
    () => new Set(stagedDrops.map(selectionGridKey)),
    [stagedDrops],
  );
  const displaySelections = useMemo(
    () => selectedCourses.filter((c) => !dropKeys.has(c.id)),
    [selectedCourses, dropKeys],
  );
  const gridCourses = useMemo(
    () => mergeGridCourses(displaySelections, stagedAdds.map((a) => a.course)),
    [displaySelections, stagedAdds],
  );
  const visualCount = gridCourses.filter(
    (c) => c.class_time !== null && c.class_time.some((slot) => slot !== ""),
  ).length;
  const totals = useMemo(
    () => totalCreditsAndHours(gridCourses),
    [gridCourses],
  );

  // ---- browse integration ----
  const pickStateOf = useCallback(
    (course: CourseOut): "selected" | "staged" | "failed" | null => {
      if (course.code !== null && failedCodes.has(course.code)) return "failed";
      if (course.code !== null && selectedShorts.has(course.code)) return "selected";
      if (stagedAdds.some((a) => a.course.id === course.id)) return "staged";
      return null;
    },
    [failedCodes, selectedShorts, stagedAdds],
  );

  const reprioritize = (rows: StagedAdd[]): StagedAdd[] =>
    rows.map((row, index) => ({ ...row, priority: index + 1 }));

  const onToggleCourse = useCallback(
    (course: CourseOut) => {
      if (stagedAdds.some((a) => a.course.id === course.id)) {
        setStagedAdds((prev) => reprioritize(prev.filter((a) => a.course.id !== course.id)));
        if (course.code !== null) {
          setFailedCodes((prev) => {
            if (!prev.has(course.code as string)) return prev;
            const next = new Set(prev);
            next.delete(course.code as string);
            return next;
          });
        }
        setPreview(null);
        return;
      }
      const selRow = items.find(
        (item) => item.state === "選上" && selectionShortCode(item) === course.code,
      );
      if (selRow !== undefined) {
        const key = selectionGridKey(selRow);
        setStagedDrops((prev) =>
          prev.some((d) => selectionGridKey(d) === key)
            ? prev.filter((d) => selectionGridKey(d) !== key)
            : [...prev, selRow],
        );
        setPreview(null);
        return;
      }
      setStagedAdds((prev) => [...prev, { course, priority: prev.length + 1 }]);
      setPreview(null);
    },
    [stagedAdds, items],
  );

  const restageFailed = (course: CourseOut) => {
    setStagedAdds((prev) => reprioritize([...prev, { course, priority: prev.length + 1 }]));
    setFailedAdds((prev) => prev.filter((c) => c.id !== course.id));
    setFailedCodes((prev) => {
      if (course.code === null) return prev;
      const next = new Set(prev);
      next.delete(course.code);
      return next;
    });
    setPreview(null);
  };

  const dismissFailed = (course: CourseOut) => {
    setFailedAdds((prev) => prev.filter((c) => c.id !== course.id));
    setFailedCodes((prev) => {
      if (course.code === null) return prev;
      const next = new Set(prev);
      next.delete(course.code);
      return next;
    });
  };

  const toggleDrop = useCallback(
    (item: SelectionItem) => {
      const key = selectionGridKey(item);
      setStagedDrops((prev) =>
        prev.some((d) => selectionGridKey(d) === key)
          ? prev.filter((d) => selectionGridKey(d) !== key)
          : [...prev, item],
      );
      setPreview(null);
    },
    [],
  );

  const clearStaging = useCallback(() => {
    setStagedAdds([]);
    setStagedDrops([]);
    setFailedAdds([]);
    setFailedCodes(new Set());
    setPreview(null);
    setPreviewError(null);
  }, []);

  // ---- png ----
  const onPng = () => {
    const node = gridRef.current;
    if (node === null || pngState === "busy") return;
    setPngError(null);
    setPngState("busy");
    downloadGridPng(node, null, visualCount)
      .catch((err: unknown) =>
        setPngError(err instanceof Error ? err.message : String(err)),
      )
      .finally(() => setPngState("idle"));
  };

  // ---- send flow ----
  const stagedCount = stagedAdds.length + stagedDrops.length;
  const canSend =
    authed && stage?.writable === true && stagedCount > 0 && phase !== "previewing";

  const onPreview = useCallback(() => {
    if (!authed || csrfToken === null || phase === "previewing") return;
    setPhase("previewing");
    setPreviewError(null);
    setPreview(null);
    const { ops, unaddable } = toWriteOps(stagedAdds, stagedDrops);
    if (ops.length === 0) {
      setPreviewError(
        unaddable.length > 0
          ? tx(
              `${unaddable.length} 門課程目錄尚未取得課別代號，暫時無法送出（${unaddable.map((c) => c.name_zh ?? c.id).join("、")}）。`,
              `${unaddable.length} course(s) have no section code in the catalog and can't be submitted (${unaddable.map((c) => c.name_zh ?? c.id).join(", ")}).`,
            )
          : tx("沒有可送出的操作。", "Nothing staged to submit."),
      );
      setPhase("idle");
      return;
    }
    previewWrite(ops, csrfToken)
      .then((body) => {
        setPhase("idle");
        if (body.writable && body.confirm_token !== null) {
          setPreview(body);
          setPhase("confirm");
        } else {
          setPreview(body);
        }
      })
      .catch((err: unknown) => {
        setPhase("idle");
        if (err instanceof ApiError && err.status === 503) {
          setPreviewError(tx("學校系統異常，稍後再試", "The school system is unavailable right now"));
        } else if (!(err instanceof ApiError) || err.status !== 401) {
          setPreviewError(tx("預檢失敗，請稍後再試", "Preview failed. Please try again shortly"));
        }
      });
  }, [authed, csrfToken, phase, stagedAdds, stagedDrops, tx]);

  const onConfirm = useCallback(() => {
    if (preview?.confirm_token == null || csrfToken === null || submitting || password === "") {
      return;
    }
    setSubmitting(true);
    setSendError(null);
    submitWrite(preview.confirm_token, password, csrfToken)
      .then((body) => {
        setJob(null);
        setPhase("job");
        setFailedAdds([]);
        setFailedCodes(new Set());
        const jobId = body.job_id;
        const poll = (): void => {
          void fetchWriteJob(jobId, csrfToken)
            .then((view) => {
              setJob(view);
              if (JOB_TERMINAL.has(view.status)) {
                setSubmitting(false);
                const successAdd = new Set(
                  view.ops.filter((o) => o.action === "+" && o.outcome === "success").map((o) => o.code),
                );
                const failed = new Set(
                  view.ops.filter((o) => o.outcome === "failed" || o.outcome === "parse_failed").map((o) => o.code),
                );
                setFailedAdds(
                  stagedAdds
                    .filter((a) => a.course.code !== null && failed.has(a.course.code))
                    .map((a) => a.course),
                );
                setStagedAdds((prev) =>
                  reprioritize(
                    prev.filter(
                      (a) =>
                        a.course.code === null ||
                        (!successAdd.has(a.course.code) && !failed.has(a.course.code)),
                    ),
                  ),
                );
                setStagedDrops((prev) =>
                  prev.filter((d) => {
                    const short = selectionShortCode(d);
                    return short !== null && failed.has(short);
                  }),
                );
                setFailedCodes(failed);
                setPreview(null);
                setPreviewError(null);
                onSync();
                if (view.reconcile !== null) setJobNote(tx("部分結果需要重新對帳；已自動同步已選。", "Some results need a fresh reconcile; selections were re-synced automatically."));
              } else {
                window.setTimeout(poll, POLL_MS);
              }
            })
            .catch(() => {
              setJobNote(tx("狀態查詢暫時失敗，稍候會自動重試。", "Status check failed temporarily; it will retry automatically."));
              window.setTimeout(poll, POLL_MS * 2);
            });
        };
        poll();
      })
      .catch((err: unknown) => {
        setSubmitting(false);
        setSendError(
          err instanceof ApiError
            ? String(err.detail ?? err.message)
            : tx("送出失敗，請稍後再試", "Submit failed. Please try again shortly"),
        );
      })
      .finally(() => setPassword(""));
  }, [preview, csrfToken, submitting, password, clearStaging, onSync, tx]);

  const dropConfirmReady = preview?.confirm_token != null && password !== "";

  const segmentedTabs = (
    <div className="studio-segmented-tabs" role="tablist" aria-label={tx("右側功能切換", "Right panel view switch")}>
      <button
        type="button"
        role="tab"
        aria-selected={tab === "browse"}
        className={`segmented-tab-btn ${tab === "browse" ? "active" : ""}`}
        onClick={() => setTab("browse")}
      >
        <Search size={13} className="me-1.5" />
        <span>{tx("查課探索", "Find Courses")}</span>
      </button>
      <button
        type="button"
        role="tab"
        aria-selected={tab === "selections"}
        className={`segmented-tab-btn ${tab === "selections" ? "active" : ""}`}
        onClick={() => setTab("selections")}
      >
        <BookmarkCheck size={13} className="me-1.5" />
        <span>{tx("已選課程", "My Selections")}</span>
        {items.length > 0 && <span className="tab-count-pill ms-1.5">{items.length}</span>}
      </button>
    </div>
  );

  // ============================== RENDER ==============================
  if (!authed) {
    return (
      <div className="row justify-content-center py-5">
        <div className="col-12 col-md-8 col-lg-5 text-center">
          <div className="card shadow-sm border-0 rounded-4">
            <div className="card-body p-4">
              <h2 className="h5 fw-bold text-dark">{tx("選課主控台", "Course-selection Console")}</h2>
              <p className="text-muted small mb-3">{tx("登入後才能檢視你的真實課表、暫存加退選操作並送出選課。", "Sign in to see your real timetable, stage add/drop operations, and submit them.")}</p>
              <Link to="/login" className="btn btn-brand rounded-pill px-4">{tx("前往登入", "Go to sign-in")}</Link>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="row g-3">
      {/* LEFT: unified timetable canvas + send bar */}
      <div className="col-12 col-xl-7">
        <div className="schedule-canvas-pane">
          <div className="schedule-canvas-header d-flex align-items-center justify-content-between flex-wrap py-2.5 px-3.5" style={{ gap: "1rem" }}>
            <div className="d-flex align-items-center flex-wrap" style={{ gap: "1rem" }}>
              <div className="schedule-canvas-title" style={{ gap: "0.55rem" }}>
                <CalendarCheck size={18} className="text-teal-600" />
                <span>{tx("目前課表", "Current Timetable")}</span>
              </div>
              <div className="d-inline-flex align-items-center px-3 py-1 bg-slate-100 rounded-pill border text-slate-700 fw-bold" style={{ fontSize: "0.82rem", gap: "0.6rem" }}>
                <span>{tx(`已選 ${totals.courseCount} 門`, `${totals.courseCount} courses`)}</span>
                <span className="text-slate-400">·</span>
                <span>{tx(`${totals.totalCredits} 學分`, `${totals.totalCredits} cr`)}</span>
                <span className="text-slate-400">·</span>
                <span>{tx(`${totals.totalHours} 節`, `${totals.totalHours} hrs`)}</span>
              </div>
            </div>

            <div className="d-flex align-items-center flex-wrap" style={{ gap: "1.25rem" }}>
              <button
                type="button"
                className="btn btn-sm btn-outline-brand rounded-pill px-3.5 py-1.5 d-inline-flex align-items-center fw-semibold shadow-xs"
                style={{ fontSize: "0.84rem", gap: "0.55rem" }}
                onClick={onPng}
                disabled={pngState === "busy" || visualCount === 0}
              >
                <Download size={14} />
                <span>{pngState === "busy" ? tx("匯出中…", "Exporting…") : tx("下載課表圖", "Download PNG")}</span>
              </button>

              <div className="d-flex align-items-center" style={{ gap: "0.75rem" }}>
                <span className="text-muted d-none d-sm-inline" style={{ fontSize: "0.78rem" }} role="status">
                  {syncedAt === null ? tx("尚未同步", "Not synced") : tx(`同步：${formatSyncedTime(syncedAt)}`, `Synced: ${formatSyncedTime(syncedAt)}`)}
                </span>
                <button
                  type="button"
                  className="btn btn-sm btn-outline-secondary rounded-pill px-3 py-1.5 d-inline-flex align-items-center fw-semibold"
                  style={{ fontSize: "0.84rem", gap: "0.5rem" }}
                  onClick={onSync}
                  disabled={syncing}
                  title={syncedAt ? `上次同步：${syncedAt}` : undefined}
                >
                  <ArrowRepeat size={13} className={syncing ? "spin" : ""} />
                  <span>{syncing ? tx("同步中…", "Syncing…") : tx("同步", "Sync")}</span>
                </button>
              </div>
            </div>
          </div>

          {syncError !== null && (
            <div className="alert alert-warning py-1.5 px-3 mx-3 mt-2 small rounded-3" role="alert">{syncError}</div>
          )}
          {reconcileNote !== null && (
            <div className="alert alert-info py-1.5 px-3 mx-3 mt-2 small rounded-3" role="status">{reconcileNote}</div>
          )}
          {pngError !== null && (
            <div className="alert alert-warning py-1.5 px-3 mx-3 mt-2 small rounded-3" role="alert">{pngError}</div>
          )}

          <div className="schedule-grid-scroll-container">
            <div ref={gridRef} className="w-100">
              <ScheduleTable
                selectedCourses={gridCourses}
                hoveredCourseId={hoveredCourseId}
                onCourseHover={setHoveredCourseId}
                onCourseRemove={() => undefined}
                readOnly
                previewCourse={previewCourse}
              />
            </div>
          </div>

          {/* staged drops chips (undoable) */}
          {stagedDrops.length > 0 && (
            <div className="d-flex flex-wrap align-items-center gap-2 px-3 pb-2">
              <span className="badge text-bg-danger rounded-pill">{tx("待退選", "Droppable")} {stagedDrops.length}</span>
              {stagedDrops.map((item) => (
                <button
                  key={selectionGridKey(item)}
                  type="button"
                  className="btn btn-sm btn-outline-danger rounded-pill py-0 px-2 d-inline-flex align-items-center gap-1"
                  onClick={() => toggleDrop(item)}
                  title={tx("點擊還原", "Click to undo")}
                  style={{ fontSize: "0.74rem" }}
                >
                  <span className="text-decoration-line-through">{shortName(item)}</span>
                  <span className="font-monospace">{selectionShortCode(item) ?? ""}</span>
                </button>
              ))}
            </div>
          )}

          {/* failed adds from the last batch (not on your timetable; retry or drop) */}
          {failedAdds.length > 0 && (
            <div className="d-flex flex-wrap align-items-center gap-2 px-3 pb-2" data-testid="failed-adds-strip">
              <span className="badge bg-red-100 text-red-800 border border-red-300 rounded-pill">
                {tx("送出失敗", "Submit failed")} {failedAdds.length}
              </span>
              {failedAdds.map((course) => (
                <span
                  key={course.id}
                  className="btn btn-sm btn-outline-danger rounded-pill py-0 px-2 d-inline-flex align-items-center gap-1"
                  style={{ fontSize: "0.74rem" }}
                >
                  <span>{shortName(course)}</span>
                  <span className="font-monospace">{course.code ?? ""}</span>
                  <button
                    type="button"
                    className="btn btn-link p-0 border-0 text-success fw-bold text-decoration-none ms-1"
                    style={{ fontSize: "0.72rem" }}
                    title={tx("放回暫存重試", "Stage again to retry")}
                    aria-label={tx(`放回 ${shortName(course)} 至暫存`, `Restage ${shortName(course)}`)}
                    onClick={() => restageFailed(course)}
                  >
                    {tx("放回", "Retry")}
                  </button>
                  <button
                    type="button"
                    className="btn btn-link p-0 border-0 text-danger fw-bold text-decoration-none"
                    style={{ fontSize: "0.72rem" }}
                    title={tx("移除", "Dismiss")}
                    aria-label={tx(`移除 ${shortName(course)}`, `Dismiss ${shortName(course)}`)}
                    onClick={() => dismissFailed(course)}
                  >
                    {tx("移除", "Dismiss")}
                  </button>
                </span>
              ))}
            </div>
          )}

          {/* send bar */}
          <div className="d-flex flex-wrap align-items-center justify-content-between gap-2 px-3 py-3 border-top">
            <div className="d-flex align-items-center gap-2 flex-wrap">
              <span
                className={`badge rounded-pill ${
                  stage === null
                    ? "text-bg-secondary"
                    : stage.writable
                      ? "bg-emerald-100 text-emerald-800 border border-emerald-300"
                      : "bg-secondary-subtle text-secondary border"
                }`}
              >
                {stage === null
                  ? tx("階段資訊載入中…", "Loading stage info…")
                  : stage.writable
                    ? tx(`可送單（${stage.stage}）`, `Writable now (${stage.stage})`)
                    : tx(`目前非可寫階段（${stage.stage}）`, `Not in a writable stage (${stage.stage})`)}
              </span>
              {stagedCount > 0 && (
                <span className="small text-muted">
                  ＋{stagedAdds.length} {tx("加選", "add")} · −{stagedDrops.length} {tx("退選", "drop")}
                </span>
              )}
            </div>
            <div className="d-flex align-items-center gap-2">
              <button
                type="button"
                className="btn btn-sm btn-outline-secondary rounded-pill d-inline-flex align-items-center gap-1"
                onClick={clearStaging}
                disabled={stagedCount === 0 || phase !== "idle"}
              >
                <Eraser size={12} />
                <span>{tx("清空", "Clear all")}</span>
              </button>
              <button
                type="button"
                className="btn btn-brand btn-sm rounded-pill px-3 shadow-sm d-inline-flex align-items-center gap-1"
                onClick={onPreview}
                disabled={!canSend}
                data-testid="console-preview"
              >
                <Send size={12} />
                <span>{tx("預覽並送出", "Preview & submit")}</span>
              </button>
            </div>
          </div>

          {/* preview-blocked verdict panel (inline, no modal) */}
          {preview !== null && !preview.writable && phase === "idle" && (
            <div className="alert alert-danger mx-3 mb-3 py-2 px-3 small rounded-3" role="alert">
              <div className="fw-semibold mb-1">{tx("此批次無法送出", "This batch cannot be submitted")}</div>
              <ul className="mb-0 ps-3">
                {preview.ops.map((op) =>
                  op.verdict !== "ok" ? (
                    <li key={`${op.index}-${op.code}`}>
                      <span className="font-monospace">{op.code ?? op.course_id}</span>
                      {"："}{op.verdict}
                      {op.detail !== null ? `（${op.detail}）` : ""}
                    </li>
                  ) : null,
                )}
              </ul>
            </div>
          )}
          {previewError !== null && (
            <div className="alert alert-danger mx-3 mb-3 py-2 px-3 small rounded-3" role="alert">{previewError}</div>
          )}

          {/* job result panel */}
          {phase === "job" && (
            <div className="px-3 pb-3">
              <div className="card border-0 rounded-4 bg-light-subtle">
                <div className="card-body py-3">
                  <div className="d-flex align-items-center gap-2 mb-2">
                    {job === null || !JOB_TERMINAL.has(job.status) ? (
                      <>
                        <HourglassSplit className="text-teal-600" />
                        <span className="fw-semibold small">{tx(`送單執行中${job !== null ? `（${job.status}）` : ""}…`, `Submitting${job !== null ? ` (${job.status})` : ""}…`)}</span>
                      </>
                    ) : job.status === "done" ? (
                      <>
                        <CheckCircleFill className="text-success" />
                        <span className="fw-semibold small">{tx("送單完成", "Submission finished")}</span>
                      </>
                    ) : (
                      <>
                        <XCircleFill className="text-danger" />
                        <span className="fw-semibold small">
                          {tx(
                            `送單${job.status === "cancelled" ? "已取消" : "失敗"}（${job.status}）`,
                            `Submission ${job.status === "cancelled" ? "cancelled" : "failed"} (${job.status})`,
                          )}
                        </span>
                      </>
                    )}
                  </div>
                  {job !== null && (
                    <ul className="small mb-0 ps-3">
                      {job.ops.map((op, i) => {
                        const copy = outcomeCopy(op.outcome);
                        const toneClass =
                          copy.tone === "success"
                            ? "text-success"
                            : copy.tone === "danger"
                              ? "text-danger"
                              : copy.tone === "warning"
                                ? "text-warning-emphasis"
                                : "text-secondary";
                        return (
                          <li key={`${op.code}-${i}`}>
                            <span className="font-monospace">{op.code}</span>
                            {" "}{op.action === "+" ? tx("加選", "Add") : tx("退選", "Drop")}：
                            <span className={`fw-semibold ${toneClass}`}>{copy.label}</span>
                            {op.school_msg !== null && op.outcome !== "success" ? (
                              <span className="text-muted d-block" style={{ whiteSpace: "pre-wrap" }}>
                                {tx("原因：", "Reason: ")}{op.school_msg}
                              </span>
                            ) : null}
                          </li>
                        );
                      })}
                    </ul>
                  )}
                  {jobNote !== null && <p className="text-muted small mb-0 mt-1">{jobNote}</p>}
                  {unplaced.length > 0 && (
                    <p className="text-muted small mb-0 mt-1">
                      {tx(
                        `${unplaced.length} 門「選上」課程時間資料無法解析，未排入課表。`,
                        `${unplaced.length} held course(s) have unparseable time data and were left off the grid.`,
                      )}
                    </p>
                  )}
                </div>
              </div>
            </div>
          )}

        </div>
      </div>

      {/* RIGHT: two-tab side panel */}
      <div className="col-12 col-xl-5">
        {tab === "browse" ? (
          <CourseBrowser
            hoveredCourseId={hoveredCourseId}
            onCourseHover={setHoveredCourseId}
            onCoursePreview={setPreviewCourse}
            baseCourses={gridCourses}
            pickState={pickStateOf}
            onToggleCourse={onToggleCourse}
            onViewCourse={setDetailCourse}
            headerTopSlot={segmentedTabs}
          />
        ) : (
          <section className="selections-pane-container" aria-label={tx("我的已選課程", "My selections")}>
            <div className="discovery-search-header">
              <div className="pb-2">{segmentedTabs}</div>
              <div className="d-flex align-items-center justify-content-between pt-1">
                <span className="fw-bold text-dark small">{tx("已選課程（同步自學校）", "Selections (synced from the school)")}</span>
                <button
                  type="button"
                  className="btn btn-sm btn-brand d-inline-flex align-items-center gap-1 rounded-pill px-3"
                  onClick={onSync}
                  disabled={syncing}
                >
                  <ArrowRepeat size={12} className={syncing ? "spin" : ""} />
                  <span>{syncing ? tx("同步中…", "Syncing…") : tx("同步我的已選", "Sync my selections")}</span>
                </button>
              </div>
            </div>

            <div className="p-3 overflow-y-auto flex-grow-1">
              {loading ? (
                <p className="text-muted small mb-0 p-3 text-center bg-light rounded-3">{tx("讀取中…", "Loading…")}</p>
              ) : syncedAt === null ? (
                <p className="text-muted small mb-0 p-3 text-center bg-light rounded-3">{tx("尚未同步。按下「同步我的已選」從學校系統讀取。", "Not synced yet. Hit “Sync my selections” to pull from the school.")}</p>
              ) : items.length === 0 ? (
                <p className="text-muted small mb-0 p-3 text-center bg-light rounded-3">{tx("學校系統目前無任何已選紀錄。", "No selections on the school system right now.")}</p>
              ) : (
                <ul className="list-unstyled mb-0">
                  {items.map((item) => {
                    const dropped = stagedDrops.some(
                      (d) => selectionGridKey(d) === selectionGridKey(item),
                    );
                    return (
                      <li
                        key={`${selectionGridKey(item)}-${item.state}`}
                        className="selection-card d-flex justify-content-between align-items-start gap-2"
                      >
                        <div className="min-w-0">
                          <div className={`fw-semibold small ${dropped ? "text-decoration-line-through text-muted" : "text-dark"}`}>
                            {item.name}
                            <span className="badge text-bg-light border ms-1 font-monospace" style={{ fontSize: "0.68rem" }}>
                              {selectionShortCode(item) ?? item.code ?? ""}
                            </span>
                            {item.unknown && (
                              <span className="badge text-bg-secondary ms-1" style={{ fontSize: "0.68rem" }}>{tx("目錄查無此課", "Not in catalog")}</span>
                            )}
                          </div>
                          <div className="text-muted" style={{ fontSize: "0.74rem" }}>
                            {[item.times, item.room ?? item.room_text, item.teacher, item.credit !== null ? (lang === "en" ? `${item.credit} cr` : `${item.credit} 學分`) : null]
                              .filter((p): p is string => p !== null && p !== "")
                              .join(" · ")}
                          </div>
                        </div>
                        <div className="d-flex flex-column align-items-end gap-1 flex-shrink-0">
                          <span
                            className={`badge ${item.state === "選上" ? "bg-emerald-100 text-emerald-800 border border-emerald-300" : "text-bg-light border"}`}
                            style={{ fontSize: "0.7rem" }}
                          >
                            {item.state}
                          </span>
                          {item.state === "選上" && (
                            <button
                              type="button"
                              className={`btn btn-sm rounded-pill ${dropped ? "btn-outline-success" : "btn-outline-danger"}`}
                              onClick={() => toggleDrop(item)}
                              style={{ fontSize: "0.72rem" }}
                            >
                              {dropped ? tx("還原", "Undo") : tx("退選", "Drop")}
                            </button>
                          )}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          </section>
        )}
      </div>

      {/* course detail + syllabus modal */}
      {detailCourse !== null && (
        <CourseDetailModal course={detailCourse} onClose={() => setDetailCourse(null)} />
      )}

      {/* confirm modal */}
      {phase === "confirm" && preview !== null && preview.confirm_token !== null && (
        <>
          <div className="crs-modal-backdrop" onClick={() => { if (!submitting) setPhase("idle"); }} />
          <div className="crs-modal" role="dialog" aria-modal="true" aria-labelledby="console-confirm-title">
            <div className="crs-modal-card card shadow-lg border-0 rounded-4" style={{ maxWidth: "34rem", width: "100%" }}>
              <div className="card-body p-4">
                <h2 className="h5 fw-bold mb-2 text-dark" id="console-confirm-title">{tx("二次確認：送出選課操作", "Confirm before submitting")}</h2>
                <p className="text-muted small mb-3">{tx(`將送出以下 ${preview.ops.length} 筆操作；送去學校系統後結果以學校回應為準。`, `About to submit ${preview.ops.length} operation(s); once sent, the school's response is final.`)}</p>
                <ul className="small mb-3 ps-3" data-testid="console-confirm-list">
                  {preview.ops.map((op) => {
                    const isAdd = op.action === "+";
                    const addRow = stagedAdds.find((a) => a.course.code === op.code);
                    const dropRow = items.find(
                      (it) => selectionShortCode(it) === op.code && it.state === "選上",
                    );
                    const name = addRow !== undefined
                      ? addRow.course.name_zh ?? addRow.course.name_en
                      : dropRow?.name ?? null;
                    return (
                      <li key={`${op.code}-${op.index}`} className="mb-1">
                        <span className={`badge me-1 ${isAdd ? "text-bg-primary" : "text-bg-danger"}`}>
                          {isAdd ? tx("＋加選", "+ Add") : tx("−退選", "− Drop")}
                        </span>
                        <span className="fw-semibold text-dark">{name ?? op.code}</span>
                        <span className="text-muted ms-1 font-monospace">{op.code}</span>
                        {isAdd && addRow !== undefined && (
                          <span className="text-muted ms-1">{tx(`（志願 ${addRow.priority}）`, `(priority ${addRow.priority})`)}</span>
                        )}
                        {op.quota !== null && op.quota.remaining === 0 && (
                          <span className="badge text-bg-warning ms-1">{tx("額滿警示", "Full — quota warning")}</span>
                        )}
                        {op.verdict !== "ok" && (
                          <span className="badge text-bg-danger ms-1">{op.verdict}</span>
                        )}
                      </li>
                    );
                  })}
                </ul>
                {preview.warnings.length > 0 && (
                  <div className="text-warning-emphasis small mb-2" role="alert">
                    <ExclamationTriangleFill size={12} className="me-1" />
                    {tx(
                      `名額資料為目錄快照${preview.quota_as_of !== null ? `（${preview.quota_as_of}）` : ""}，實際以學校系統為準。`,
                      `Availability is a catalog snapshot${preview.quota_as_of !== null ? ` (${preview.quota_as_of})` : ""}; the school system decides`,
                    )}
                  </div>
                )}
                <div className="mb-3">
                  <label htmlFor="console-confirm-password" className="form-label small fw-semibold text-dark mb-1">
                    {tx("重新輸入選課密碼", "Re-enter your course password")}
                  </label>
                  <input
                    id="console-confirm-password"
                    type="password"
                    className="form-control"
                    autoComplete="current-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    autoFocus
                  />
                </div>
                {sendError !== null && (
                  <div className="alert alert-danger py-1.5 px-3 small rounded-3 mb-3" role="alert">{sendError}</div>
                )}
                <div className="d-flex justify-content-end gap-2">
                  <button
                    type="button"
                    className="btn btn-outline-secondary btn-sm rounded-pill px-3"
                    onClick={() => { if (!submitting) { setPhase("idle"); setSendError(null); } }}
                    disabled={submitting}
                  >
                    {tx("取消", "Cancel")}
                  </button>
                  <button
                    type="button"
                    className="btn btn-brand btn-sm rounded-pill px-3"
                    onClick={onConfirm}
                    disabled={!dropConfirmReady || submitting}
                    data-testid="console-confirm-submit"
                  >
                    {submitting ? tx("送出中…", "Submitting…") : tx("確認送出", "Confirm & submit")}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

export default HomePage;
