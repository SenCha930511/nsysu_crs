/**
 * /write → 送單紀錄 (records): owner-scoped job history, newest first.
 * Redesigned with Next-Gen NSYSU Studio design language, clean card structures,
 * sanitized error messages, and formatted timestamps.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowRepeat,
  CheckCircleFill,
  Clock,
  ClockHistory,
  ExclamationCircleFill,
  ExclamationTriangleFill,
  HourglassSplit,
  Layers,
  SendCheck,
  XCircleFill,
} from "react-bootstrap-icons";

import { ApiError, fetchWriteJobs } from "../lib/api";
import type { JobView } from "../lib/api";
import { useI18n } from "../lib/i18n";
import { outcomeCopy } from "../lib/writeOps";
import { useAuth } from "../state/auth";

/** Strip raw JavaScript, HTML tags, and noisy markup from school responses. */
function cleanSchoolMessage(raw: string | null): string {
  if (!raw) return "";
  let cleaned = raw.replace(/-->\s*function[\s\S]*?;\s*}/gi, "");
  cleaned = cleaned.replace(/function\s*\w*\s*\([^)]*\)\s*\{[\s\S]*?\}/gi, "");
  cleaned = cleaned.replace(/<[^>]+>/g, " ");
  cleaned = cleaned.replace(/&nbsp;/gi, " ");
  cleaned = cleaned.replace(/&lt;/gi, "<");
  cleaned = cleaned.replace(/&gt;/gi, ">");
  cleaned = cleaned.replace(/&amp;/gi, "&");
  cleaned = cleaned.replace(/\s+/g, " ").trim();
  return cleaned;
}

/** Formats an ISO string into human-readable YYYY/MM/DD HH:mm:ss in local time. */
function formatTimestamp(iso: string | null): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    const pad = (n: number) => String(n).padStart(2, "0");
    const y = d.getFullYear();
    const m = pad(d.getMonth() + 1);
    const date = pad(d.getDate());
    const h = pad(d.getHours());
    const min = pad(d.getMinutes());
    const s = pad(d.getSeconds());
    return `${y}/${m}/${date} ${h}:${min}:${s}`;
  } catch {
    return iso;
  }
}

/** Computes duration between start and finish. */
function formatDuration(startIso: string, endIso: string | null): string | null {
  if (!endIso) return null;
  try {
    const start = new Date(startIso).getTime();
    const end = new Date(endIso).getTime();
    if (isNaN(start) || isNaN(end) || end < start) return null;
    const diffMs = end - start;
    if (diffMs < 1000) return `${diffMs} ms`;
    return `${(diffMs / 1000).toFixed(2)} s`;
  } catch {
    return null;
  }
}

function JobCard({ job }: { job: JobView }) {
  const { tx } = useI18n();

  const statusInfo = (() => {
    switch (job.status) {
      case "done":
        return {
          label: tx("已完成", "Finished"),
          badgeClass: "bg-emerald-50 text-emerald-700 border border-emerald-200",
          icon: CheckCircleFill,
        };
      case "failed":
        return {
          label: tx("執行失敗", "Failed"),
          badgeClass: "bg-rose-50 text-rose-700 border border-rose-200",
          icon: XCircleFill,
        };
      case "cancelled":
        return {
          label: tx("已取消", "Cancelled"),
          badgeClass: "bg-slate-100 text-slate-700 border border-slate-200",
          icon: ExclamationCircleFill,
        };
      case "queued":
        return {
          label: tx("排隊中", "Queued"),
          badgeClass: "bg-amber-50 text-amber-700 border border-amber-200",
          icon: HourglassSplit,
        };
      case "running":
        return {
          label: tx("執行中", "Running"),
          badgeClass: "bg-teal-50 text-teal-700 border border-teal-200",
          icon: ArrowRepeat,
        };
      case "session_superseded":
        return {
          label: tx("已被新登入覆蓋", "Session superseded"),
          badgeClass: "bg-rose-50 text-rose-700 border border-rose-200",
          icon: ExclamationTriangleFill,
        };
      default:
        return {
          label: job.status,
          badgeClass: "bg-slate-100 text-slate-700 border border-slate-200",
          icon: Clock,
        };
    }
  })();

  const StatusIcon = statusInfo.icon;
  const duration = formatDuration(job.created_at, job.finished_at);

  return (
    <article className="record-job-card">
      <div className="record-job-header">
        <div className="d-flex align-items-center gap-2 flex-wrap">
          <span className={`badge rounded-pill px-2.5 py-1.5 d-inline-flex align-items-center gap-1.5 fw-bold ${statusInfo.badgeClass}`}>
            <StatusIcon size={12} />
            <span>{statusInfo.label}</span>
          </span>

          {job.reconcile !== null && (
            <span className="badge bg-amber-100 text-amber-900 border border-amber-300 rounded-pill px-2.5 py-1">
              {tx("需重新對帳", "Reconcile needed")}
            </span>
          )}

          <span className="badge text-bg-light border text-muted font-monospace" style={{ fontSize: "0.75rem" }}>
            #{job.job_id.slice(0, 8)}
          </span>
        </div>

        <div className="d-flex align-items-center gap-2 text-muted" style={{ fontSize: "0.82rem" }}>
          <Clock size={13} className="text-secondary" />
          <span className="fw-semibold">{formatTimestamp(job.created_at)}</span>
          {duration !== null && (
            <span className="badge bg-slate-100 text-slate-600 border border-slate-200 rounded-pill px-2">
              {tx(`耗時 ${duration}`, `took ${duration}`)}
            </span>
          )}
        </div>
      </div>

      <div className="record-job-body">
        {job.message !== null && (
          <div className="text-muted small px-1">
            {job.message}
          </div>
        )}

        <div className="d-flex flex-column gap-2">
          {job.ops.map((op, index) => {
            const copy = outcomeCopy(op.outcome);
            const isSuccess = copy.tone === "success";
            const isDanger = copy.tone === "danger";
            const isWarning = copy.tone === "warning";
            const sanitizedReason = cleanSchoolMessage(op.school_msg);

            return (
              <div key={`${op.code}-${index}`} className="record-op-row">
                <div className="d-flex align-items-center justify-content-between flex-wrap gap-2 w-100">
                  <div className="d-flex align-items-center gap-2 flex-wrap">
                    {op.action === "+" ? (
                      <span className="badge bg-teal-100 text-teal-800 border border-teal-300 rounded-pill px-2.5 py-1 fw-bold">
                        {tx("加選", "Add")}
                      </span>
                    ) : (
                      <span className="badge bg-rose-100 text-rose-800 border border-rose-300 rounded-pill px-2.5 py-1 fw-bold">
                        {tx("退選", "Drop")}
                      </span>
                    )}

                    {op.priority !== null && (
                      <span className="badge bg-indigo-50 text-indigo-700 border border-indigo-200 rounded-pill px-2 py-1 font-monospace fw-bold" style={{ fontSize: "0.76rem" }}>
                        {tx(`志願 ${op.priority}`, `P${op.priority}`)}
                      </span>
                    )}

                    <span className="font-monospace fw-bold text-dark px-1" style={{ fontSize: "0.95rem" }}>
                      {op.code}
                    </span>
                  </div>

                  <div className="d-flex align-items-center gap-1.5">
                    <span
                      className={`badge rounded-pill px-2.5 py-1.5 fw-bold ${
                        isSuccess
                          ? "bg-emerald-50 text-emerald-700 border border-emerald-300"
                          : isDanger
                            ? "bg-rose-50 text-rose-700 border border-rose-300"
                            : isWarning
                              ? "bg-amber-50 text-amber-800 border border-amber-300"
                              : "bg-slate-100 text-slate-700 border border-slate-300"
                      }`}
                    >
                      {copy.label}
                    </span>
                  </div>
                </div>

                {sanitizedReason !== "" && op.outcome !== "success" && (
                  <div className="record-reason-box">
                    <div className="d-flex align-items-start gap-1.5">
                      <ExclamationCircleFill size={13} className="flex-shrink-0 mt-0.5" />
                      <div>
                        <strong>{tx("學校回報原因：", "School rejection reason: ")}</strong>
                        <span>{sanitizedReason}</span>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </article>
  );
}

function RecordsPage() {
  const { tx } = useI18n();
  const { csrfToken } = useAuth();
  const [jobs, setJobs] = useState<JobView[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [errorText, setErrorText] = useState<string | null>(null);

  const load = useCallback(() => {
    if (csrfToken === null) return;
    setLoading(true);
    setErrorText(null);
    fetchWriteJobs(csrfToken)
      .then((rows) => setJobs(rows))
      .catch((err: unknown) => {
        if (!(err instanceof ApiError) || err.status !== 401) {
          setErrorText(tx("無法讀取送單紀錄，請稍後再試", "Couldn't load submission history. Please try again shortly"));
        }
      })
      .finally(() => setLoading(false));
  }, [csrfToken, tx]);

  useEffect(() => {
    load();
  }, [load]);

  const summary = useMemo(() => {
    if (!jobs || jobs.length === 0) return null;
    const totalJobs = jobs.length;
    const successfulJobs = jobs.filter((j) => j.status === "done").length;
    const lastJobTime = formatTimestamp(jobs[0]?.created_at ?? null);
    return { totalJobs, successfulJobs, lastJobTime };
  }, [jobs]);

  return (
    <div className="studio-canvas-container py-3">
      <div className="row justify-content-center">
        <div className="col-12 col-xl-10">
          {/* Header Card */}
          <div className="card shadow-sm border-0 rounded-4 mb-4">
            <div className="card-body p-4">
              <div className="d-flex align-items-center justify-content-between flex-wrap gap-3">
                <div>
                  <h1 className="h4 fw-bold mb-1 text-dark d-flex align-items-center gap-2.5">
                    <div className="p-2 rounded-3 bg-teal-50 text-teal-700 d-inline-flex align-items-center justify-content-center">
                      <ClockHistory size={22} />
                    </div>
                    <span>{tx("送單紀錄", "Submission History")}</span>
                  </h1>
                  <p className="text-muted mb-0" style={{ fontSize: "0.88rem" }}>
                    {tx(
                      "檢視您所有選課志願單的送出歷程、執行狀態與校方系統回傳結果。",
                      "Review your submitted batch histories, execution status, and verbatim school responses.",
                    )}
                  </p>
                </div>

                <div className="d-flex align-items-center gap-2">
                  <button
                    type="button"
                    className="btn btn-brand rounded-pill px-3.5 py-1.5 d-inline-flex align-items-center gap-1.5 shadow-sm"
                    style={{ fontSize: "0.88rem" }}
                    onClick={load}
                    disabled={loading}
                  >
                    <ArrowRepeat size={14} className={loading ? "spin-animation" : ""} />
                    <span>{loading ? tx("同步中…", "Refreshing…") : tx("更新紀錄", "Refresh")}</span>
                  </button>
                </div>
              </div>

              {summary !== null && (
                <div className="d-flex align-items-center flex-wrap gap-2.5 mt-3 pt-3 border-top">
                  <div className="selected-stat-chip">
                    <SendCheck size={14} className="text-teal-600" />
                    <span>{tx(`總送單 ${summary.totalJobs} 批次`, `Total ${summary.totalJobs} batches`)}</span>
                  </div>
                  <div className="selected-stat-chip">
                    <CheckCircleFill size={14} className="text-emerald-600" />
                    <span>{tx(`完成 ${summary.successfulJobs} 批次`, `Finished ${summary.successfulJobs} batches`)}</span>
                  </div>
                  <div className="selected-stat-chip">
                    <Clock size={14} className="text-secondary" />
                    <span>{tx(`最新送單：${summary.lastJobTime}`, `Latest: ${summary.lastJobTime}`)}</span>
                  </div>
                </div>
              )}
            </div>
          </div>

          {errorText !== null && (
            <div className="alert alert-danger py-2.5 px-3.5 rounded-3 mb-4 d-flex align-items-center gap-2" role="alert">
              <ExclamationCircleFill size={16} />
              <span>{errorText}</span>
            </div>
          )}

          {jobs === null && loading ? (
            <div className="card shadow-sm border-0 rounded-4 p-5 text-center text-muted">
              <div className="d-inline-flex align-items-center justify-content-center mb-2">
                <HourglassSplit size={24} className="text-teal-600 spin-animation" />
              </div>
              <p className="mb-0 fw-semibold">{tx("讀取選單送出紀錄中…", "Loading submission history…")}</p>
            </div>
          ) : jobs !== null && jobs.length === 0 ? (
            <div className="card shadow-sm border-0 rounded-4 p-5 text-center text-muted">
              <div className="p-3 bg-slate-100 text-slate-400 rounded-circle d-inline-flex align-items-center justify-content-center mx-auto mb-3" style={{ width: "56px", height: "56px" }}>
                <Layers size={24} />
              </div>
              <h3 className="h6 fw-bold text-dark mb-1">{tx("尚無任何送單紀錄", "No Submissions Yet")}</h3>
              <p className="small mb-0 text-muted">
                {tx(
                  "於「查課・課表」排定志願並送出後，所有的批次執行歷程與校方結果將完整記錄於此。",
                  "Once you queue and submit your schedule from Courses & Timetable, all execution details and feedback will appear here.",
                )}
              </p>
            </div>
          ) : (
            <div className="records-list-container">
              {jobs?.map((job) => <JobCard key={job.job_id} job={job} />)}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default RecordsPage;
