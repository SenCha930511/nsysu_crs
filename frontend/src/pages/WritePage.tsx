/**
 * /write: 送單中心 (todo 16).
 *
 * Flow: GET /api/stage 階段閘門 -> ops 組裝（主課表加選＋已選退選，退選需
 * 逐列輸入 8 碼課號）-> POST /api/write/preview 逐列判定 -> 阻擋為 0 才可
 * 進入二次確認 modal（重打密碼＋退選碼再確認）-> POST /api/write/submit ->
 * GET /api/write/jobs/{id} 每 2 秒輪詢至終態 -> 逐課結果如實呈現學校原文
 * -> 「重新同步已選」對帳（staged 意圖 vs 學校最新真相）。
 *
 * All rule logic and ALL copy tables live in ../lib/writeOps (pure, vitest-
 * locked); this file is the renderer. 密碼只存在 modal 當次輸入的 local
 * state，從不落地、從不進 context。
 */

import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import type { Dispatch } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRepeat,
  CheckCircleFill,
  ExclamationTriangleFill,
  Send,
  Trash3,
  XCircleFill,
} from "react-bootstrap-icons";

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
  JobView,
  OpVerdictOut,
  PreviewResponse,
  SelectionItem,
  StageInfo,
} from "../lib/api";
import {
  INITIAL_COMPOSER,
  buildPreviewOps,
  buildReconcileRows,
  batchWarningText,
  blockedCount,
  canConfirm,
  checkConfirmForm,
  composerReducer,
  confirmFormErrorText,
  dropIncludable,
  formatPeriods,
  isTerminalStatus,
  jobStatusCopy,
  jobTerminalBanner,
  opWarningText,
  outcomeCopy,
  priorityErrorText,
  unknownReconciledHint,
  unprioritizedAdds,
  verdictLabel,
  verdictTone,
} from "../lib/writeOps";
import type { ComposerAction, ComposerState } from "../lib/writeOps";
import { useAuth } from "../state/auth";
import { usePlansSync } from "../state/plansSync";

const POLL_INTERVAL_MS = 2000;
/** While the stage is closed, re-probe /api/stage so the gate flips itself. */
const STAGE_REPROBE_MS = 60_000;

type Phase = "compose" | "job";

interface NameMaps {
  byCourseId: Map<string, string>;
  byCode: Map<string, string>;
}

function opDisplayName(
  op: { course_id: string; code: string | null },
  names: NameMaps,
): string {
  return (
    names.byCourseId.get(op.course_id) ??
    (op.code !== null ? names.byCode.get(op.code) : undefined) ??
    op.code ??
    op.course_id
  );
}

function previewErrorText(err: unknown): string | null {
  if (!(err instanceof ApiError)) return "預檢失敗，請稍後再試";
  if (err.status === 401) return null; // global seam redirects
  if (err.status === 403) return "送單憑證（CSRF）已失效，請重新登入";
  if (err.status === 409 && err.detail === "stage_unavailable") {
    return `階段已變更（${String(err.extras.stage ?? "?")}），請重新整理階段狀態後再預檢`;
  }
  if (err.status === 400) {
    switch (err.detail) {
      case "priority_required":
      case "priority_invalid":
        return "志願序須為 1–20 的整數";
      case "priority_duplicate":
        return "志願序不可重複";
      case "priority_forbidden":
        return "退選課程不可攜帶志願序";
      case "ops_limit_exceeded":
        return "超出單批上限（加退選 15 筆／初選 10 筆）";
      case "typed_confirmation_missing":
        return "退選課號輸入不符，請逐列輸入正確的 8 碼課號";
      default:
        return `預檢內容有誤（${err.detail}）`;
    }
  }
  if (err.status === 503) return "學校系統異常，稍後再試";
  return "預檢失敗，請稍後再試";
}

// ---------- stage gate ----------

function StageGate({
  stage,
  loading,
  error,
  onRefresh,
}: {
  stage: StageInfo | null;
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
}) {
  const refreshButton = (
    <button
      type="button"
      className="btn btn-outline-secondary btn-sm"
      onClick={onRefresh}
      disabled={loading}
      aria-label="重新整理階段狀態"
    >
      <ArrowRepeat className="me-1" />
      {loading ? "偵測中…" : "重新整理"}
    </button>
  );

  let alertClass = "alert-secondary";
  let title = "階段偵測中…";
  let detail: string | null = null;
  if (error !== null) {
    alertClass = "alert-warning";
    title = "無法偵測學校選課階段";
    detail = error;
  } else if (stage !== null) {
    if (stage.writable) {
      alertClass = "alert-success";
      title =
        stage.stage === "加退選"
          ? "目前為選課開放期間：加退選"
          : `目前為選課開放期間：${stage.stage}`;
      detail = `表單 ${stage.variant ?? "?"} ．偵測時間 ${stage.checked_at}`;
    } else if (stage.need_confirmation) {
      alertClass = "alert-warning";
      title = "請先至學校系統完成必修課程確認";
      detail = `學校系統偵測到必修課程確認前置（階段：${stage.stage}），完成後請重新整理`;
    } else if (stage.stage === "關閉") {
      alertClass = "alert-warning";
      title = "目前為選課關閉期間";
      detail = `學校系統目前未開放加退選（偵測時間 ${stage.checked_at}）；開放後此處會自動更新`;
    } else if (stage.stage === "初選") {
      alertClass = "alert-warning";
      title = "初選志願代送尚未開放";
      detail = "本站代送功能於初選階段暫不開放，請改用學校系統登記志願";
    } else {
      alertClass = "alert-warning";
      title = "學校選課頁面格式異動";
      detail = "無法判定目前選課階段，送單功能已暫停";
    }
  }

  return (
    <div className={`alert ${alertClass} d-flex align-items-start gap-2 rounded-4 shadow-sm`} role="status">
      <div className="flex-grow-1">
        <div className="fw-bold" data-testid="stage-title">
          {title}
          {stage !== null && (
            <span className="badge text-bg-secondary ms-2">{stage.stage}</span>
          )}
        </div>
        {detail !== null && <div className="small mt-1">{detail}</div>}
      </div>
      {refreshButton}
    </div>
  );
}

// ---------- ops composer ----------

function RemainingBadge({ remaining }: { remaining: number | null }) {
  if (remaining === null) return <span className="badge text-bg-light border">餘 –</span>;
  return remaining > 0 ? (
    <span className="badge text-bg-success">餘 {remaining}</span>
  ) : (
    <span className="badge text-bg-danger">額滿</span>
  );
}

function ComposerSection({
  composer,
  dispatch,
  disabled,
}: {
  composer: ComposerState;
  dispatch: Dispatch<ComposerAction>;
  disabled: boolean;
}) {
  const unprio = unprioritizedAdds(composer);
  const prioError = priorityErrorText(composer.priorityError);

  return (
    <fieldset disabled={disabled}>
      <section className="mb-4">
        <h3 className="h6 fw-bold">
          加選（來自主課表，{composer.adds.length} 門）
        </h3>
        {prioError !== null && (
          <div className="alert alert-danger py-1 small" role="alert">
            {prioError}
          </div>
        )}
        {unprio.length > 0 && (
          <div className="alert alert-warning py-1 small" role="status">
            {unprio.length} 門未排志願序，將不會納入本批送單；請至「課表組合」
            或於下方輸入 1–20 志願序。
          </div>
        )}
        {composer.adds.length === 0 ? (
          <p className="text-muted small mb-0">
            主課表尚無課程。請先到「查課·課表」把課程加入課表，或到「我的已選」同步後退選。
          </p>
        ) : (
          <div className="table-responsive">
            <table className="table table-sm align-middle mb-0">
              <thead>
                <tr>
                  <th style={{ width: "4.5rem" }}>志願序</th>
                  <th>課程</th>
                  <th style={{ width: "5rem" }} />
                </tr>
              </thead>
              <tbody>
                {composer.adds.map((add) => (
                  <tr key={add.courseId} data-testid={`add-row-${add.courseId}`}>
                    <td>
                      <input
                        type="text"
                        inputMode="numeric"
                        className="form-control form-control-sm priority-input"
                        aria-label={`志願序：${add.course?.name_zh ?? add.courseId}`}
                        defaultValue={add.priority ?? ""}
                        key={`${add.courseId}:${add.priority ?? "null"}`}
                        placeholder="–"
                        onBlur={(event) =>
                          dispatch({
                            type: "setPriority",
                            courseId: add.courseId,
                            raw: event.target.value,
                          })
                        }
                      />
                    </td>
                    <td>
                      <div className="fw-semibold">
                        {add.course?.name_zh ?? "未知課程（已不在課目錄）"}
                        {add.code !== null && (
                          <span className="text-muted small ms-2">{add.code}</span>
                        )}
                      </div>
                      <div className="text-muted small">
                        {[
                          add.course?.teacher ?? null,
                          add.course !== null ? formatPeriods(add.course.class_time) : "",
                        ]
                          .filter((part) => part !== null && part !== "")
                          .join(" · ") || "目錄查無此課"}
                      </div>
                    </td>
                    <td className="text-end">
                      <RemainingBadge remaining={add.course?.remaining ?? null} />
                      <button
                        type="button"
                        className="btn btn-sm btn-link text-danger ms-1 p-1"
                        aria-label="從本批移除"
                        onClick={() =>
                          dispatch({ type: "removeAdd", courseId: add.courseId })
                        }
                      >
                        <Trash3 />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section>
        <h3 className="h6 fw-bold">
          退選（來自已選同步，{composer.drops.length} 門候選）
        </h3>
        {composer.drops.length === 0 ? (
          <p className="text-muted small mb-0">
            沒有可退選的課程（已選同步為空或皆為失敗紀錄）。
          </p>
        ) : (
          <div className="table-responsive">
            <table className="table table-sm align-middle mb-0">
              <thead>
                <tr>
                  <th>課程</th>
                  <th style={{ width: "13rem" }}>輸入 8 碼課號以確認退選</th>
                </tr>
              </thead>
              <tbody>
                {composer.drops.map((drop) => {
                  const matched = dropIncludable(drop);
                  return (
                    <tr
                      key={drop.key}
                      data-testid={`drop-row-${drop.key}`}
                      className={matched ? "table-danger" : undefined}
                    >
                      <td>
                        <div className="fw-semibold">
                          {drop.name}
                          <span className="text-muted small ms-2">{drop.code}</span>
                          <span
                            className={`badge ms-1 ${
                              drop.state === "登記加選"
                                ? "text-bg-info"
                                : "text-bg-success"
                            }`}
                          >
                            {drop.state}
                          </span>
                          {matched && (
                            <span className="badge text-bg-danger ms-1">將退選</span>
                          )}
                        </div>
                      </td>
                      <td>
                        <input
                          type="text"
                          className={`form-control form-control-sm${
                            drop.typed !== "" && !matched ? " is-invalid" : ""
                          }`}
                          aria-label={`確認退選課號：${drop.confirmCode}`}
                          placeholder={drop.confirmCode}
                          value={drop.typed}
                          onChange={(event) =>
                            dispatch({
                              type: "setDropTyped",
                              key: drop.key,
                              typed: event.target.value,
                            })
                          }
                        />
                        {drop.typed !== "" && !matched && (
                          <div className="invalid-feedback">課號不符</div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </fieldset>
  );
}

// ---------- preview verdicts ----------

function VerdictIcon({ tone }: { tone: string }) {
  if (tone === "blocked") return <XCircleFill className="text-danger" />;
  if (tone === "warn") return <ExclamationTriangleFill className="text-warning" />;
  return <CheckCircleFill className="text-success" />;
}

function PreviewSection({
  preview,
  names,
}: {
  preview: PreviewResponse;
  names: NameMaps;
}) {
  const blocked = blockedCount(preview);
  return (
    <section className="mt-3" data-testid="preview-results">
      <h3 className="h6 fw-bold">
        預檢結果
        {blocked > 0 ? (
          <span className="badge text-bg-danger ms-2">{blocked} 筆遭阻擋</span>
        ) : (
          <span className="badge text-bg-success ms-2">全部通過</span>
        )}
      </h3>
      {preview.warnings.map((warning) => (
        <div className="alert alert-warning py-1 small" role="status" key={warning}>
          {batchWarningText(warning, preview.quota_as_of)}
        </div>
      ))}
      <div className="table-responsive">
        <table className="table table-sm align-middle mb-0">
          <tbody>
            {preview.ops.map((op) => (
              <VerdictRow key={op.index} op={op} names={names} />
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function VerdictRow({ op, names }: { op: OpVerdictOut; names: NameMaps }) {
  const tone = verdictTone(op);
  const rowClass =
    tone === "blocked" ? "table-danger" : tone === "warn" ? "table-warning" : "";
  return (
    <tr className={rowClass} data-testid={`verdict-row-${op.index}`} data-tone={tone}>
      <td style={{ width: "2rem" }}>
        <VerdictIcon tone={tone} />
      </td>
      <td style={{ width: "4rem" }}>
        <span className={`badge ${op.action === "+" ? "text-bg-primary" : "text-bg-danger"}`}>
          {op.action === "+" ? "加選" : "退選"}
        </span>
      </td>
      <td>
        <span className="fw-semibold">{opDisplayName(op, names)}</span>
        {op.code !== null && <span className="text-muted small ms-2">{op.code}</span>}
      </td>
      <td className="small">
        <div className="fw-semibold">{verdictLabel(op)}</div>
        {op.warnings.map((warning) => (
          <div key={warning} className="text-warning-emphasis">
            {opWarningText(warning)}
          </div>
        ))}
      </td>
    </tr>
  );
}

// ---------- confirm modal ----------

function ConfirmModal({
  preview,
  composer,
  names,
  onCancel,
  onConfirm,
}: {
  preview: PreviewResponse;
  composer: ComposerState;
  names: NameMaps;
  onCancel: () => void;
  onConfirm: (password: string) => Promise<string | null>;
}) {
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const dropRows = composer.drops.filter((d) =>
    preview.ops.some((op) => op.action === "-" && op.code === d.code),
  );
  const formCheck = checkConfirmForm(password, dropRows);

  const submit = async () => {
    if (!formCheck.ok || pending) return;
    setPending(true);
    setError(null);
    try {
      const err = await onConfirm(password);
      if (err !== null) setError(err);
    } finally {
      setPassword(""); // 密碼只用於當次，送出不留存
      setPending(false);
    }
  };

  return (
    <>
      <div className="crs-modal-backdrop" onClick={onCancel} />
      <div
        className="crs-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-modal-title"
      >
        <div className="crs-modal-card card shadow-lg border-0 rounded-4">
          <div className="card-body p-4">
            <h2 id="confirm-modal-title" className="h5 fw-bold mb-2 text-dark">
              二次確認：送出選課操作
            </h2>
            <p className="text-muted small mb-3">
              將送出以下 {preview.ops.length} 筆操作；送出後進入排隊，結果以學校系統回應為準。
            </p>
            <ul className="small mb-3 ps-3" data-testid="confirm-diff-list">
              {preview.ops.map((op) => (
                <li key={op.index} className="mb-1">
                  {op.action === "+" ? (
                    <>
                      <span className="badge text-bg-primary me-1">＋加選</span>
                      <span className="fw-semibold text-dark">{opDisplayName(op, names)}</span>
                      {(() => {
                        const add = composer.adds.find(
                          (a) => a.courseId === op.course_id,
                        );
                        return add !== undefined && add.priority !== null ? (
                          <span className="text-muted ms-1">（志願 {add.priority}）</span>
                        ) : null;
                      })()}
                    </>
                  ) : (
                    <>
                      <span className="badge text-bg-danger me-1">−退選</span>
                      <span className="fw-semibold text-dark">{opDisplayName(op, names)}</span>
                    </>
                  )}
                </li>
              ))}
            </ul>

            {dropRows.length > 0 && (
              <div className="mb-3 p-3 bg-light rounded-3" data-testid="confirm-drop-codes">
                <div className="small fw-semibold mb-1 text-dark">退選課號確認</div>
                {dropRows.map((drop) => (
                  <div
                    key={drop.key}
                    className="d-flex align-items-center gap-2 small mb-1"
                    data-testid={`confirm-drop-${drop.key}`}
                  >
                    <span className="font-monospace fw-bold">{drop.confirmCode}</span>
                    <span>{drop.name}</span>
                    {dropIncludable(drop) ? (
                      <span className="badge text-bg-success">課號一致</span>
                    ) : (
                      <span className="badge text-bg-danger">課號不符</span>
                    )}
                  </div>
                ))}
              </div>
            )}

            <div className="mb-3">
              <label htmlFor="confirm-password" className="form-label small fw-semibold text-dark mb-1">
                重新輸入選課密碼
              </label>
              <input
                id="confirm-password"
                type="password"
                className="form-control"
                autoComplete="off"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="密碼僅用於本次身分驗證，不會被儲存"
              />
            </div>

            {!formCheck.ok && password.length > 0 && formCheck.error !== null && (
              <div className="alert alert-danger py-1.5 px-3 small rounded-3 mb-3" role="alert">
                {confirmFormErrorText(formCheck.error)}
              </div>
            )}
            {error !== null && (
              <div className="alert alert-danger py-1 small" role="alert">
                {error}
              </div>
            )}

            <div className="d-flex justify-content-end gap-2">
              <button
                type="button"
                className="btn btn-outline-secondary btn-sm"
                onClick={onCancel}
                disabled={pending}
              >
                取消
              </button>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={() => void submit()}
                disabled={!formCheck.ok || pending}
                data-testid="confirm-submit"
              >
                <Send className="me-1" />
                {pending ? "送出中…" : "確認送單"}
              </button>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

// ---------- job progress / results / reconcile ----------

interface ReconcileState {
  syncing: boolean;
  syncedAt: string | null;
  added: number;
  removed: number;
  rows: ReturnType<typeof buildReconcileRows> | null;
}

function JobPanel({
  job,
  replayed,
  names,
  reconcile,
  onReconcile,
  onNewBatch,
}: {
  job: JobView;
  replayed: boolean;
  names: NameMaps;
  reconcile: ReconcileState;
  onReconcile: () => void;
  onNewBatch: () => void;
}) {
  const statusCopy = jobStatusCopy(job.status);
  const terminal = isTerminalStatus(job.status);
  const banner = jobTerminalBanner(job);

  return (
    <section className="card shadow-sm border-0 rounded-4 mb-4" data-testid="job-panel">
      <div className="card-body p-4">
        <div className="d-flex align-items-center gap-2 flex-wrap">
          <h2 className="h5 fw-bold mb-0 text-dark">送單進度</h2>
          <span className={`badge text-bg-${statusCopy.tone}`} data-testid="job-status">
            {statusCopy.label}
          </span>
          {!terminal && (
            <span className="spinner-border spinner-border-sm text-secondary" role="status" aria-label="進行中" />
          )}
          {terminal && (
            <button
              type="button"
              className="btn btn-outline-primary btn-sm ms-auto"
              onClick={onNewBatch}
            >
              重新預檢新批次
            </button>
          )}
        </div>

        <p className="text-muted small mt-2 mb-2">
          排入佇列：{job.created_at}
          {job.started_at !== null && <> · 開始執行：{job.started_at}</>}
          {job.finished_at !== null && <> · 結束：{job.finished_at}</>}
        </p>

        {replayed && (
          <div className="alert alert-info py-2 small" role="status" data-testid="replay-notice">
            此批已確認過（同樣內容不重複送出），以下為原批次的送單進度。
          </div>
        )}
        {banner !== null && (
          <div
            className={`alert py-2 small ${
              job.status === "session_superseded" ? "alert-warning" : "alert-danger"
            }`}
            role="alert"
            data-testid="job-banner"
          >
            {banner}
          </div>
        )}
        {!terminal && (
          <p className="small text-muted mb-2" role="status">
            {job.status === "queued"
              ? "批次已排入佇列，等待執行（每生序列送出）…"
              : "正在逐課送往學校系統…"}
          </p>
        )}

        <h3 className="h6 small text-muted mb-1">逐課結果</h3>
        <div className="table-responsive">
          <table className="table table-sm align-middle mb-0">
            <tbody>
              {job.ops.map((op) => {
                const copy = outcomeCopy(op.outcome);
                const name = names.byCode.get(op.code) ?? op.code;
                return (
                  <tr
                    key={`${op.action}-${op.code}`}
                    data-testid={`result-row-${op.code}`}
                    data-outcome={op.outcome ?? "pending"}
                  >
                    <td style={{ width: "4rem" }}>
                      <span
                        className={`badge ${op.action === "+" ? "text-bg-primary" : "text-bg-danger"}`}
                      >
                        {op.action === "+" ? "加選" : "退選"}
                      </span>
                    </td>
                    <td>
                      <span className="fw-semibold">{name}</span>
                      <span className="text-muted small ms-2">{op.code}</span>
                      {op.priority !== null && (
                        <span className="text-muted small ms-1">志願 {op.priority}</span>
                      )}
                    </td>
                    <td className="small" style={{ width: "50%" }}>
                      <span className={`badge text-bg-${copy.tone}`}>{copy.label}</span>
                      {op.outcome === "unknown-reconciled" && (
                        <div className="mt-1 text-warning-emphasis">
                          {unknownReconciledHint(job.reconcile)}
                        </div>
                      )}
                      {copy.hint !== null && op.outcome !== "unknown-reconciled" && (
                        <div className="mt-1 text-muted">{copy.hint}</div>
                      )}
                      {op.outcome === "parse_failed" && op.school_msg !== null ? (
                        <details className="mt-1">
                          <summary className="text-muted">原文摘錄</summary>
                          <pre className="small bg-light border rounded p-2 mt-1 mb-0 text-wrap">
                            {op.school_msg}
                          </pre>
                        </details>
                      ) : (
                        op.school_msg !== null && (
                          <div
                            className="mt-1 font-monospace small"
                            data-testid={`school-msg-${op.code}`}
                          >
                            學校訊息：「{op.school_msg}」
                          </div>
                        )
                      )}
                      {op.outcome === "階段逾時" && terminal && (
                        <button
                          type="button"
                          className="btn btn-outline-primary btn-sm mt-1"
                          onClick={onNewBatch}
                        >
                          重新預檢
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {terminal && job.status !== "session_superseded" && (
          <div className="mt-3 border-top pt-3" data-testid="reconcile-widget">
            <div className="d-flex align-items-center gap-2 flex-wrap">
              <h3 className="h6 fw-bold mb-0">對帳</h3>
              <button
                type="button"
                className="btn btn-outline-secondary btn-sm"
                onClick={onReconcile}
                disabled={reconcile.syncing}
              >
                <ArrowRepeat className="me-1" />
                {reconcile.syncing ? "同步中…" : "重新同步已選"}
              </button>
              {job.reconcile === "manual_resync_needed" && (
                <span className="badge text-bg-warning" data-testid="reconcile-hint">
                  有課程結果不明，請同步對帳
                </span>
              )}
            </div>
            {reconcile.rows !== null && (
              <>
                <p className="text-muted small mt-2 mb-1">
                  已同步（{reconcile.syncedAt}）：新增 {reconcile.added}｜移除{" "}
                  {reconcile.removed} ｜ 對照本批意圖如下
                </p>
                <div className="table-responsive">
                  <table className="table table-sm align-middle mb-0">
                    <thead>
                      <tr>
                        <th>課號</th>
                        <th>本批意圖</th>
                        <th>學校最新狀態</th>
                        <th>核對</th>
                      </tr>
                    </thead>
                    <tbody>
                      {reconcile.rows.map((row) => (
                        <tr
                          key={row.code}
                          className={row.match ? "table-success" : "table-danger"}
                          data-testid={`reconcile-row-${row.code}`}
                        >
                          <td>
                            {row.actualName ?? names.byCode.get(row.code) ?? row.code}
                            <span className="text-muted small ms-1">{row.code}</span>
                          </td>
                          <td>{row.intentLabel}</td>
                          <td>{row.actualState ?? "已選清單無此課"}</td>
                          <td>
                            {row.match ? (
                              <span className="badge text-bg-success">一致</span>
                            ) : (
                              <span className="badge text-bg-danger">不一致</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </section>
  );
}

// ---------- page ----------

function WritePage() {
  const { status: authStatus, csrfToken } = useAuth();
  const { orderedItems, hydrated } = usePlansSync();

  const [phase, setPhase] = useState<Phase>("compose");
  const [stage, setStage] = useState<StageInfo | null>(null);
  const [stageLoading, setStageLoading] = useState(true);
  const [stageError, setStageError] = useState<string | null>(null);
  const [selections, setSelections] = useState<SelectionItem[]>([]);
  const [selectionsLoaded, setSelectionsLoaded] = useState(false);

  const [composer, dispatch] = useReducer(composerReducer, INITIAL_COMPOSER);
  const composerInitRef = useRef(false);

  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [previewSig, setPreviewSig] = useState<string | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const [modalOpen, setModalOpen] = useState(false);
  const [job, setJob] = useState<JobView | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobError, setJobError] = useState<string | null>(null);
  const [pollHalted, setPollHalted] = useState(false);
  const [replayed, setReplayed] = useState(false);
  const [reconcile, setReconcile] = useState<ReconcileState>({
    syncing: false,
    syncedAt: null,
    added: 0,
    removed: 0,
    rows: null,
  });

  const loadStage = useCallback(async () => {
    setStageLoading(true);
    setStageError(null);
    try {
      const body = await fetchStage();
      setStage(body);
    } catch (err) {
      if (err instanceof ApiError && err.status === 503) {
        setStageError("學校系統異常，稍後再試");
      } else if (!(err instanceof ApiError) || err.status !== 401) {
        setStageError("無法取得階段狀態，請稍後再試");
      }
      // 401 -> global seam redirects
    } finally {
      setStageLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    void loadStage();
    fetchSelections()
      .then((body) => {
        if (cancelled) return;
        setSelections(body.items);
        setSelectionsLoaded(true);
      })
      .catch(() => {
        if (cancelled) return;
        setSelections([]);
        setSelectionsLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [loadStage]);

  // Closed stages flip automatically: re-probe every 60s while not writable.
  const stageWritable = stage?.writable ?? false;
  useEffect(() => {
    if (stageWritable || stageError !== null) return;
    const timer = window.setInterval(() => void loadStage(), STAGE_REPROBE_MS);
    return () => window.clearInterval(timer);
  }, [stageWritable, stageError, loadStage]);

  // Composer seeds once boot data (plan + selections) has landed.
  useEffect(() => {
    if (composerInitRef.current || !hydrated || !selectionsLoaded) return;
    composerInitRef.current = true;
    dispatch({ type: "reinit", planItems: orderedItems, selectionItems: selections });
  }, [hydrated, selectionsLoaded, orderedItems, selections]);

  const names = useMemo<NameMaps>(() => {
    const byCourseId = new Map<string, string>();
    const byCode = new Map<string, string>();
    for (const add of composer.adds) {
      const name = add.course?.name_zh ?? null;
      if (name === null) continue;
      byCourseId.set(add.courseId, name);
      if (add.code !== null) byCode.set(add.code, name);
    }
    for (const drop of composer.drops) {
      byCode.set(drop.code, drop.name);
      if (drop.courseId !== null) byCourseId.set(drop.courseId, drop.name);
    }
    return { byCourseId, byCode };
  }, [composer]);

  const opsNow = buildPreviewOps(composer);
  const opsSig = JSON.stringify(opsNow);
  const previewStale = preview !== null && previewSig !== opsSig;
  const writableNow =
    authStatus === "authed" && stageWritable && csrfToken !== null;
  const confirmReady = canConfirm(preview) && !previewStale && writableNow;

  const runPreview = async () => {
    if (csrfToken === null || previewing) return;
    setPreviewing(true);
    setPreviewError(null);
    try {
      const body = await previewWrite(opsNow, csrfToken);
      setPreview(body);
      setPreviewSig(opsSig);
    } catch (err) {
      const text = previewErrorText(err);
      if (text !== null) setPreviewError(text);
      setPreview(null);
      setPreviewSig(null);
    } finally {
      setPreviewing(false);
    }
  };

  // Poll the job every 2s until a terminal status lands: a self-scheduling
  // timeout chain (one poll per interval AFTER each response), so the queue
  // progression is actually visible and the endpoint is not hammered.
  useEffect(() => {
    if (phase !== "job" || jobId === null || csrfToken === null || pollHalted) {
      return;
    }
    let cancelled = false;
    let timer: number | null = null;
    const tick = () => {
      fetchWriteJob(jobId, csrfToken)
        .then((view) => {
          if (cancelled) return;
          setJob(view);
          setJobError(null);
          if (!isTerminalStatus(view.status)) {
            timer = window.setTimeout(tick, POLL_INTERVAL_MS);
          }
        })
        .catch((err: unknown) => {
          if (cancelled) return;
          setPollHalted(true);
          if (err instanceof ApiError && err.status === 403) {
            setJobError("送單憑證（CSRF）已失效，請重新登入");
          } else if (err instanceof ApiError && err.status === 404) {
            setJobError("查無此送單批次（可能已被取代或清除）");
          } else if (!(err instanceof ApiError) || err.status !== 401) {
            setJobError("無法讀取送單進度，請稍後再試");
          }
        });
    };
    tick();
    return () => {
      cancelled = true;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [phase, jobId, csrfToken, pollHalted]);

  const submitBatch = useCallback(
    async (password: string): Promise<string | null> => {
      if (csrfToken === null || preview === null || preview.confirm_token === null) {
        return "預檢結果已失效，請重新預檢";
      }
      try {
        const result = await submitWrite(preview.confirm_token, password, csrfToken);
        setJob(null);
        setJobId(result.job_id);
        setReplayed(false);
        setPollHalted(false);
        setReconcile({ syncing: false, syncedAt: null, added: 0, removed: 0, rows: null });
        setModalOpen(false);
        setPhase("job");
        return null;
      } catch (err) {
        if (!(err instanceof ApiError)) return "送出失敗，請稍後再試";
        if (err.status === 401 && err.detail === "invalid_credentials") {
          return `密碼驗證失敗${
            typeof err.extras.school_msg === "string"
              ? `（${err.extras.school_msg}）`
              : ""
          }；請重新輸入`;
        }
        if (err.status === 409 && err.detail === "duplicate_active_job") {
          const existingJobId =
            typeof err.extras.job_id === "string" ? err.extras.job_id : null;
          setJob(null);
          setJobId(existingJobId);
          setReplayed(true);
          setPollHalted(false);
          setReconcile({ syncing: false, syncedAt: null, added: 0, removed: 0, rows: null });
          setModalOpen(false);
          setPhase("job");
          return null;
        }
        if (err.status === 409 && err.detail === "confirm_token_unknown") {
          setPreview(null);
          setPreviewSig(null);
          setModalOpen(false);
          setPhase("compose");
          return null;
        }
        if (err.status === 401) return null; // global seam redirects
        if (err.status === 403) return "送單憑證（CSRF）已失效，請重新登入";
        if (err.status === 503) return "學校系統異常，稍後再試（未送出）";
        return "送出失敗，請稍後再試";
      }
    },
    [csrfToken, preview],
  );

  const runReconcile = useCallback(() => {
    if (job === null || reconcile.syncing) return;
    setReconcile((prev) => ({ ...prev, syncing: true }));
    syncSelections()
      .then((body) => {
        setReconcile({
          syncing: false,
          syncedAt: body.synced_at,
          added: body.added.length,
          removed: body.removed.length,
          rows: buildReconcileRows(job.ops, body.items),
        });
      })
      .catch(() => setReconcile((prev) => ({ ...prev, syncing: false })));
  }, [job, reconcile.syncing]);

  const backToCompose = useCallback(() => {
    setPhase("compose");
    setJob(null);
    setJobId(null);
    setReplayed(false);
    setPreview(null);
    setPreviewSig(null);
    setPollHalted(false);
    setJobError(null);
    void loadStage();
  }, [loadStage]);

  return (
    <div className="w-100 pb-4">
      <div className="card shadow-sm border-0 rounded-4 mb-3">
          <div className="card-body p-4">
            <h2 className="h5 fw-bold mb-3 text-dark d-flex align-items-center gap-2">
              <Send className="text-teal-600" size={18} />
              <span>送單中心</span>
            </h2>
            <StageGate
              stage={stage}
              loading={stageLoading}
              error={stageError}
              onRefresh={() => void loadStage()}
            />
            {authStatus === "authed" && csrfToken === null && (
              <div className="alert alert-warning py-2 px-3 small rounded-3" role="alert" data-testid="csrf-missing">
                本次登入缺少送單憑證（CSRF token），無法使用送單功能；請
                <Link to="/login" className="alert-link ms-1">重新登入</Link>
                以取得憑證。
              </div>
            )}

            {phase === "compose" && (
              <>
                {!stageWritable && stage !== null && (
                  <p className="text-muted small p-3 bg-light rounded-3 mb-3" data-testid="composer-disabled-hint">
                    目前非可寫入階段，以下送單功能全部暫停；階段開放後會自動恢復。
                  </p>
                )}
                <ComposerSection
                  composer={composer}
                  dispatch={dispatch}
                  disabled={!writableNow}
                />
                <div className="d-flex align-items-center gap-2 mt-4 pt-3 border-top flex-wrap">
                  <button
                    type="button"
                    className="btn btn-brand btn-sm px-3.5 py-1.5 shadow-sm"
                    onClick={() => void runPreview()}
                    disabled={!writableNow || previewing || opsNow.length === 0}
                    data-testid="preview-button"
                  >
                    {previewing ? "預檢中…" : `預檢本批（${opsNow.length} 筆）`}
                  </button>
                  <button
                    type="button"
                    className="btn btn-success btn-sm px-3.5 py-1.5 shadow-sm"
                    onClick={() => setModalOpen(true)}
                    disabled={!confirmReady}
                    data-testid="confirm-open"
                  >
                    確認送單
                  </button>
                  {previewStale && (
                    <span className="text-warning small fw-semibold" data-testid="preview-stale">
                      批次內容已變更，請重新預檢
                    </span>
                  )}
                  {preview !== null && !previewStale && blockedCount(preview) > 0 && (
                    <span className="text-danger small fw-semibold" data-testid="confirm-blocked-hint">
                      仍有遭阻擋的課程，排除後請重新預檢
                    </span>
                  )}
                </div>
                {previewError !== null && (
                  <div className="alert alert-danger py-2 px-3 small rounded-3 mt-3" role="alert" data-testid="preview-error">
                    {previewError}
                  </div>
                )}
                {preview !== null && <PreviewSection preview={preview} names={names} />}
              </>
            )}

            {phase === "job" && jobError !== null && (
              <div className="alert alert-danger py-2 px-3 small rounded-3 mt-3" role="alert">
                {jobError}
              </div>
            )}
          </div>
        </div>

        {phase === "job" && job !== null && (
          <JobPanel
            job={job}
            replayed={replayed}
            names={names}
            reconcile={reconcile}
            onReconcile={runReconcile}
            onNewBatch={backToCompose}
          />
        )}

        {modalOpen && preview !== null && (
          <ConfirmModal
            preview={preview}
            composer={composer}
            names={names}
            onCancel={() => setModalOpen(false)}
            onConfirm={submitBatch}
          />
        )}
    </div>
  );
}

export default WritePage;
