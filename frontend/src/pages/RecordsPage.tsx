/**
 * /write → 送單紀錄 (records): owner-scoped job history, newest first. The
 * interactive write flow lives in the home console; this page is read-only
 * evidence (status + per-op outcomes with full school reasons verbatim).
 */
import { useCallback, useEffect, useState } from "react";
import { ArrowRepeat, ClockHistory, HourglassSplit } from "react-bootstrap-icons";

import { ApiError, fetchWriteJobs } from "../lib/api";
import type { JobView } from "../lib/api";
import { outcomeCopy } from "../lib/writeOps";
import { useAuth } from "../state/auth";

const JOB_STATUS: Record<string, { label: string; badge: string }> = {
  done: { label: "已完成", badge: "bg-emerald-100 text-emerald-800 border border-emerald-300" },
  failed: { label: "未完成", badge: "bg-red-100 text-red-800 border border-red-300" },
  cancelled: { label: "已取消", badge: "text-bg-light border" },
  queued: { label: "排隊中", badge: "text-bg-light border" },
  running: { label: "執行中", badge: "text-bg-light border" },
  session_superseded: {
    label: "已被新登入取消",
    badge: "bg-red-100 text-red-800 border border-red-300",
  },
};

function jobBadge(status: string): { label: string; badge: string } {
  return JOB_STATUS[status] ?? { label: status, badge: "text-bg-light border" };
}

function JobCard({ job }: { job: JobView }) {
  const statusInfo = jobBadge(job.status);
  return (
    <div className="card shadow-sm border-0 rounded-4 mb-3">
      <div className="card-body py-3 px-4">
        <div className="d-flex flex-wrap align-items-center justify-content-between gap-2 mb-2">
          <div className="d-flex align-items-center gap-2">
            <span className={`badge rounded-pill ${statusInfo.badge}`}>{statusInfo.label}</span>
            {job.reconcile !== null && (
              <span className="badge text-bg-warning">需重新對帳</span>
            )}
          </div>
          <span className="text-muted small font-monospace">
            {job.created_at}
            {job.finished_at !== null ? ` → ${job.finished_at}` : ""}
          </span>
        </div>
        {job.message !== null && <p className="text-muted small mb-2">{job.message}</p>}
        <ul className="small mb-0 ps-3">
          {job.ops.map((op, index) => {
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
              <li key={`${op.code}-${index}`} className="mb-1">
                <span className="font-monospace">{op.code}</span>
                {" "}
                {op.action === "+" ? `加選（志願 ${op.priority ?? "?"}）` : "退選"}：
                <span className={`fw-semibold ${toneClass}`}>{copy.label}</span>
                {op.school_msg !== null && op.outcome !== "success" ? (
                  <span className="text-muted d-block" style={{ whiteSpace: "pre-wrap" }}>
                    原因：{op.school_msg}
                  </span>
                ) : null}
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}

function RecordsPage() {
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
          setErrorText("無法讀取送單紀錄，請稍後再試");
        }
      })
      .finally(() => setLoading(false));
  }, [csrfToken]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="row justify-content-center">
      <div className="col-12 col-lg-9">
        <div className="d-flex align-items-center justify-content-between flex-wrap gap-2 mb-3">
          <h2 className="h5 fw-bold mb-0 text-dark d-flex align-items-center gap-2">
            <ClockHistory className="text-teal-600" size={20} />
            <span>送單紀錄</span>
          </h2>
          <button
            type="button"
            className="btn btn-sm btn-brand rounded-pill d-inline-flex align-items-center gap-1"
            onClick={load}
            disabled={loading}
          >
            <ArrowRepeat size={12} />
            <span>{loading ? "讀取中…" : "更新紀錄"}</span>
          </button>
        </div>

        {errorText !== null && (
          <div className="alert alert-warning py-2 px-3 small rounded-3 mb-3" role="alert">
            {errorText}
          </div>
        )}

        {jobs === null && loading ? (
          <p className="text-muted small p-4 text-center bg-light rounded-3 mb-0">
            <HourglassSplit size={13} className="me-1" /> 讀取中…
          </p>
        ) : jobs !== null && jobs.length === 0 ? (
          <p className="text-muted small p-4 text-center bg-light rounded-3 mb-0">
            尚無送出紀錄。於主控台組出第一批次後，這裡會出現它的執行與結果。
          </p>
        ) : (
          jobs?.map((job) => <JobCard key={job.job_id} job={job} />)
        )}
      </div>
    </div>
  );
}

export default RecordsPage;
