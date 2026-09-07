/**
 * /me → 我的資料 (personal records & profile): 歷年成績 (SCO family), 繳費狀態 and 在學證明
 * (REGWEB family). A card fetches ONLY when its availability flag came back
 * true on login/me (false also covers the FEATURE_STU_ENROLL-off backend).
 * A per-family 401 (REGWEB_EXPIRED / SCO_EXPIRED) stays in-page as an inline
 * note; the global soft-logout seam deliberately ignores those codes (see
 * lib/guards.ts). Genuine session death is redirected by the seam, so the
 * "session_dead" error kind here renders nothing.
 */
import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import {
  ArrowRepeat,
  Award,
  Building,
  CardChecklist,
  CashStack,
  CheckCircleFill,
  Clock,
  Download,
  ExclamationCircleFill,
  FileEarmarkPdf,
  InfoCircleFill,
  Mortarboard,
  MortarboardFill,
  PersonBadge,
  PersonCircle,
  Receipt,
} from "react-bootstrap-icons";

import {
  fetchGrades,
  fetchPaymentStatus,
  fetchRegistrationChecklist,
  syncGrades,
} from "../lib/api";
import type {
  GradesResponse,
  PaymentStatusResponse,
  RegistrationChecklist,
} from "../lib/api";
import { useI18n } from "../lib/i18n";
import { shouldForceRelogin } from "../lib/guards";
import { meFeatureErrorKind } from "../lib/meErrors";
import {
  checklistStatusTone,
  formatChecklistStatus,
  gradesDiffText,
  sanitizeChecklistPeriod,
  splitBilingualText,
} from "../lib/meExtras";
import { useAuth } from "../state/auth";

/** RecordsPage-style local timestamp (YYYY/MM/DD HH:mm:ss); "—" fallback. */
function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}/${pad(d.getMonth() + 1)}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  } catch {
    return iso;
  }
}

/** Per-card error copy; returns null when the global seam owns the failure. */
function cardErrorText(
  err: unknown,
  tx: (zh: string, en: string) => string,
  fallbackZh: string,
  fallbackEn: string,
): string | null {
  switch (meFeatureErrorKind(err)) {
    case "session_dead":
      return null;
    case "school_unavailable":
      return tx("學校系統異常，稍後再試", "The school system is unavailable right now");
    case "campus_connection_expired":
      return tx("校內連線已過期，請重新登入", "Campus connection expired — please sign in again");
    case "feature_off":
      return tx(
        "此帳號尚未開通此功能，請重新登入試試",
        "This feature isn't connected for your account yet — try signing in again",
      );
    default:
      return tx(fallbackZh, fallbackEn);
  }
}

/** Availability flag is false: no fetch ever ran, no error banner suffered. */
function FeatureOffNote() {
  const { tx } = useI18n();
  return (
    <div className="d-flex align-items-start gap-2 text-muted small bg-light rounded-3 p-3 border">
      <InfoCircleFill size={16} className="flex-shrink-0 mt-0.5 text-slate-400" />
      <span>
        {tx(
          "此帳號尚未開通此功能，請重新登入試試",
          "This feature isn't connected for your account yet — try signing in again",
        )}
      </span>
    </div>
  );
}

function CardErrorLine({ text }: { text: string }) {
  return (
    <div className="alert alert-warning py-2 px-3 small rounded-3 mb-3 d-flex align-items-center gap-2" role="alert">
      <ExclamationCircleFill size={15} className="flex-shrink-0 text-amber-600" />
      <span>{text}</span>
    </div>
  );
}

/** New-tab PDF open plus the popup-blocker hint (cert and receipt share it). */
function usePdfOpenNote(): { openNote: string | null; openPdf: (path: string) => void } {
  const { tx } = useI18n();
  const [openNote, setOpenNote] = useState<string | null>(null);
  const openPdf = useCallback(
    (path: string) => {
      window.open(path, "_blank");
      setOpenNote(
        tx(
          "檔案已在新分頁開啟下載；若沒有反應，請確認已允許瀏覽器的彈出式視窗。",
          "The file is opening in a new tab. If nothing appears, please check your browser's pop-up blocker.",
        ),
      );
    },
    [tx],
  );
  return { openNote, openPdf };
}

function OpenNoteAlert({ note }: { note: string | null }) {
  if (note === null) return null;
  return (
    <div className="alert alert-info py-2 px-3 small rounded-3 mt-3 mb-0 d-flex align-items-center gap-2" role="status">
      <InfoCircleFill size={14} className="flex-shrink-0 text-cyan-600" />
      <span>{note}</span>
    </div>
  );
}

function CardIcon({ children }: { children: ReactNode }) {
  return (
    <div
      className="p-2 rounded-3 bg-teal-50 text-teal-700 d-inline-flex align-items-center justify-content-center flex-shrink-0"
      style={{ width: "38px", height: "38px" }}
    >
      {children}
    </div>
  );
}

function GradesCard() {
  const { tx, lang } = useI18n();
  const { scoAvailable } = useAuth();
  const [data, setData] = useState<GradesResponse | null>(null);
  const [loading, setLoading] = useState(scoAvailable);
  const [syncing, setSyncing] = useState(false);
  const [errorText, setErrorText] = useState<string | null>(null);
  // Session-only diff note from the latest sync; remount clears it.
  const [diffNote, setDiffNote] = useState<string | null>(null);

  useEffect(() => {
    if (!scoAvailable) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    fetchGrades()
      .then((body) => {
        if (!cancelled) setData(body);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setErrorText(
          cardErrorText(
            err,
            tx,
            "無法讀取歷年成績，請稍後再試",
            "Couldn't load your grades. Please try again shortly",
          ),
        );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [scoAvailable, tx]);

  const onSync = useCallback(() => {
    if (syncing || !scoAvailable) return;
    setSyncing(true);
    setErrorText(null);
    setDiffNote(null);
    syncGrades()
      .then((body) => {
        setData({ synced_at: body.synced_at, items: body.items });
        const diff = gradesDiffText(
          body.added.length,
          body.removed.length,
          body.unchanged.length,
        );
        setDiffNote(lang === "zh" ? diff.zh : diff.en);
      })
      .catch((err: unknown) => {
        setErrorText(
          cardErrorText(err, tx, "同步失敗，請稍後再試", "Sync failed. Please try again shortly"),
        );
      })
      .finally(() => setSyncing(false));
  }, [syncing, scoAvailable, lang, tx]);

  return (
    <section className="profile-card" aria-label={tx("歷年成績", "Academic Transcript")}>
      <div className="profile-card-header">
        <div className="d-flex align-items-center gap-2.5 min-w-0 flex-grow-1">
          <CardIcon>
            <MortarboardFill size={18} />
          </CardIcon>
          <div className="min-w-0">
            <h2 className="h6 fw-bold mb-0 text-dark text-truncate">{tx("歷年成績", "Academic Transcript")}</h2>
            <span className="text-muted text-truncate d-block" style={{ fontSize: "0.78rem" }}>
              {tx("中山大學教務成績系統同步資料", "NSYSU Academic Affairs grade record snapshot")}
            </span>
          </div>
        </div>

        {scoAvailable && (
          <div className="d-flex align-items-center gap-2 card-header-actions">
            {diffNote !== null && (
              <span
                className="studio-badge studio-badge-secondary text-truncate"
                style={{ maxWidth: "260px" }}
                role="status"
              >
                {diffNote}
              </span>
            )}
            {data?.synced_at && (
              <span className="profile-sync-stamp font-monospace text-muted d-inline-flex align-items-center" role="status">
                <Clock size={12} className="text-slate-400 me-1 flex-shrink-0" />
                <span>{tx(`上次同步：${formatDateTime(data.synced_at)}`, `Synced: ${formatDateTime(data.synced_at)}`)}</span>
              </span>
            )}
            <button
              type="button"
              className="btn btn-sm btn-brand rounded-pill px-3 py-1.5 fw-semibold d-inline-flex align-items-center shadow-sm"
              style={{ fontSize: "0.82rem", gap: "0.45rem" }}
              onClick={onSync}
              disabled={syncing}
              data-testid="grades-sync"
            >
              <ArrowRepeat size={13} className={syncing ? "spin" : ""} />
              <span>{syncing ? tx("同步中…", "Syncing…") : tx("同步歷年成績", "Sync Grades")}</span>
            </button>
          </div>
        )}
      </div>

      <div className="profile-card-body">
        {errorText !== null && <CardErrorLine text={errorText} />}

        {!scoAvailable ? (
          <FeatureOffNote />
        ) : loading && data === null ? (
          <div className="p-4 text-center text-muted bg-light rounded-3">
            <div className="spinner-border spinner-border-sm text-teal-600 me-2" role="status" aria-hidden />
            <span className="fw-semibold">{tx("讀取歷年成績中…", "Loading academic transcript…")}</span>
          </div>
        ) : data === null ? null : data.items.length === 0 ? (
          <div className="text-center text-muted py-4">
            <div
              className="p-3 bg-slate-100 text-slate-400 rounded-circle d-inline-flex align-items-center justify-content-center mx-auto mb-3"
              style={{ width: "56px", height: "56px" }}
            >
              <Mortarboard size={24} />
            </div>
            <h3 className="h6 fw-bold text-dark mb-1">{tx("尚無成績資料", "No grade records yet")}</h3>
            <p className="small mb-3 text-muted" style={{ maxWidth: "26rem", margin: "0 auto" }}>
              {tx(
                "按下「同步歷年成績」即可從學校教務系統讀取你的完整歷年成績清單。",
                "Hit “Sync Grades” to pull your full grade history from the school system.",
              )}
            </p>
            <button
              type="button"
              className="btn btn-sm btn-outline-brand rounded-pill px-3.5 py-1.5 fw-semibold d-inline-flex align-items-center gap-1.5"
              onClick={onSync}
              disabled={syncing}
            >
              <ArrowRepeat size={14} className={syncing ? "spin" : ""} />
              <span>{syncing ? tx("同步中…", "Syncing…") : tx("同步歷年成績", "Sync Grades")}</span>
            </button>
          </div>
        ) : (
          <div className="profile-table-container">
            <div className="table-responsive">
              <table className="table table-hover table-sm mb-0 align-middle text-nowrap">
                <tbody>
                  {data.items.map((row, rowIndex) => (
                    <tr
                      key={rowIndex}
                      className={rowIndex === 0 ? "table-light fw-bold text-slate-800" : ""}
                    >
                      {row.map((cell, cellIndex) => (
                        <td key={cellIndex} className="py-2 px-3">
                          {cell}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

function PaymentCard() {
  const { tx } = useI18n();
  const { regwebAvailable } = useAuth();
  const [data, setData] = useState<PaymentStatusResponse | null>(null);
  const [loading, setLoading] = useState(regwebAvailable);
  const [errorText, setErrorText] = useState<string | null>(null);
  const { openNote, openPdf } = usePdfOpenNote();

  useEffect(() => {
    if (!regwebAvailable) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    fetchPaymentStatus()
      .then((body) => {
        if (!cancelled) setData(body);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setErrorText(
          cardErrorText(
            err,
            tx,
            "無法讀取繳費狀態，請稍後再試",
            "Couldn't load your billing status. Please try again shortly",
          ),
        );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [regwebAvailable, tx]);

  return (
    <section className="profile-card" aria-label={tx("繳費狀態", "Tuition & Billing")}>
      <div className="profile-card-header">
        <div className="d-flex align-items-center gap-2.5 min-w-0 flex-grow-1">
          <CardIcon>
            <CashStack size={18} />
          </CardIcon>
          <div className="min-w-0">
            <h2 className="h6 fw-bold mb-0 text-dark text-truncate">{tx("繳費狀態", "Tuition & Billing")}</h2>
            <span className="text-muted text-truncate d-block" style={{ fontSize: "0.78rem" }}>
              {tx("學雜費、各項規費繳納紀錄及收據狀態", "Tuition, fees payment records, and official receipt status")}
            </span>
          </div>
        </div>

        {data !== null && data.dept !== "" && (
          <div className="d-flex align-items-center gap-2 card-header-actions">
            <span className="studio-badge studio-badge-secondary text-truncate" style={{ maxWidth: "220px" }}>
              <Building size={12} className="text-slate-500 me-1" />
              <span>{tx("系所：", "Dept: ")}{data.dept}</span>
            </span>
          </div>
        )}
      </div>

      <div className="profile-card-body">
        {errorText !== null && <CardErrorLine text={errorText} />}

        {!regwebAvailable ? (
          <FeatureOffNote />
        ) : loading && data === null ? (
          <div className="p-4 text-center text-muted bg-light rounded-3">
            <div className="spinner-border spinner-border-sm text-teal-600 me-2" role="status" aria-hidden />
            <span className="fw-semibold">{tx("讀取繳費狀態中…", "Loading billing status…")}</span>
          </div>
        ) : data === null ? null : data.bills.length === 0 ? (
          <div className="text-center text-muted py-4">
            <div
              className="p-3 bg-slate-100 text-slate-400 rounded-circle d-inline-flex align-items-center justify-content-center mx-auto mb-3"
              style={{ width: "56px", height: "56px" }}
            >
              <CashStack size={24} />
            </div>
            <h3 className="h6 fw-bold text-dark mb-1">{tx("目前無任何待繳或繳費單據", "No bills on record")}</h3>
            <p className="small mb-0 text-muted">
              {tx("校內系統目前無需要繳納之款項或相關紀錄。", "There are currently no outstanding or historical bills in the campus system.")}
            </p>
          </div>
        ) : (
          <div className="profile-table-container">
            <div className="table-responsive">
              <table className="table table-hover table-sm mb-0 align-middle responsive-payment-table">
                <thead>
                  <tr>
                    <th scope="col">{tx("單據名稱", "Bill Item")}</th>
                    <th scope="col">{tx("應繳金額", "Amount")}</th>
                    <th scope="col">{tx("繳費狀態", "Status")}</th>
                    <th scope="col">{tx("繳費日期", "Pay Date")}</th>
                    <th scope="col">{tx("收據狀態", "Receipt")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.bills.map((bill, index) => {
                    const paid = bill.pay_date !== null && bill.pay_date !== "";
                    return (
                      <tr key={`${bill.item}-${index}`}>
                        <td data-col="item" className="fw-semibold text-dark">{bill.item}</td>
                        <td data-label={tx("應繳金額", "Amount")} className="font-monospace fw-bold text-slate-800">
                          {bill.amount ? `$${bill.amount}` : "—"}
                        </td>
                        <td data-label={tx("繳費狀態", "Status")}>
                          <span className={`studio-badge ${paid ? "studio-badge-success" : "studio-badge-warning"}`}>
                            {paid && <CheckCircleFill size={12} />}
                            <span>{bill.status}</span>
                          </span>
                        </td>
                        <td data-label={tx("繳費日期", "Pay Date")} className="font-monospace text-slate-600">
                          {bill.pay_date !== null && bill.pay_date !== "" ? bill.pay_date : "—"}
                        </td>
                        <td data-col="receipt" data-label={tx("收據狀態", "Receipt")}>
                          {bill.receipt_available ? (
                            <div className="d-flex flex-row flex-md-column align-items-center align-items-md-start gap-2 gap-md-1">
                              <span className="studio-badge studio-badge-indigo">
                                <Receipt size={12} />
                                <span>{tx("收據已開立", "Receipt Issued")}</span>
                              </span>
                              <button
                                type="button"
                                className="btn btn-sm btn-outline-brand rounded-pill px-2.5 py-0.5 d-inline-flex align-items-center gap-1"
                                style={{ fontSize: "0.76rem" }}
                                onClick={() => openPdf("/api/me/payment-receipt")}
                                data-testid={`receipt-download-${index}`}
                              >
                                <FileEarmarkPdf size={11} />
                                <span>{tx("下載收據（PDF）", "Download Receipt (PDF)")}</span>
                              </button>
                            </div>
                          ) : (
                            <span className="text-muted small">—</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}

        <OpenNoteAlert note={openNote} />
      </div>
    </section>
  );
}

function CertCard() {
  const { tx } = useI18n();
  const { regwebAvailable } = useAuth();
  const { openNote, openPdf } = usePdfOpenNote();

  const onDownload = () => openPdf("/api/me/enrollment-cert");

  return (
    <section className="profile-card" aria-label={tx("在學證明", "Enrollment Certificate")}>
      <div className="profile-card-header">
        <div className="d-flex align-items-center gap-2.5 min-w-0 flex-grow-1">
          <CardIcon>
            <Award size={18} />
          </CardIcon>
          <div className="min-w-0">
            <h2 className="h6 fw-bold mb-0 text-dark text-truncate">{tx("在學證明", "Enrollment Certificate")}</h2>
            <span className="text-muted text-truncate d-block" style={{ fontSize: "0.78rem" }}>
              {tx("由教務處網路註冊系統即時簽證產出之官方在學證明", "Official PDF certificate live-generated from Academic Affairs system")}
            </span>
          </div>
        </div>

        <div className="card-header-actions">
          <span className="studio-badge studio-badge-info">
            <CheckCircleFill size={12} />
            <span>{tx("校方電子簽證", "Live Official E-Cert")}</span>
          </span>
        </div>
      </div>

      <div className="profile-card-body">
        {!regwebAvailable ? (
          <FeatureOffNote />
        ) : (
          <div className="cert-action-banner">
            <div className="d-flex align-items-center gap-3">
              <div
                className="p-3 bg-white text-teal-700 rounded-3 border shadow-xs d-inline-flex align-items-center justify-content-center flex-shrink-0"
                style={{ width: "52px", height: "52px" }}
              >
                <FileEarmarkPdf size={28} />
              </div>
              <div>
                <h3 className="h6 fw-bold mb-1 text-dark">
                  {tx("國立中山大學在學證明書（PDF）", "NSYSU Certificate of Enrollment (PDF)")}
                </h3>
                <p className="text-muted small mb-0" style={{ lineHeight: 1.5 }}>
                  {tx(
                    "由教務處系統即時產出，包含學號、系所與最新學期註冊章，下載內容不經本網站伺服器儲存。",
                    "Generated on-demand by the school registration system with official e-seal. Never stored on our servers.",
                  )}
                </p>
              </div>
            </div>

            <div className="d-flex flex-column align-items-stretch align-items-sm-end gap-1.5 flex-shrink-0">
              <button
                type="button"
                className="btn btn-brand rounded-pill px-4 py-2 d-inline-flex align-items-center justify-content-center shadow-sm fw-semibold"
                style={{ fontSize: "0.88rem", gap: "0.55rem" }}
                onClick={onDownload}
                data-testid="cert-download"
              >
                <Download size={15} />
                <span>{tx("下載在學證明（PDF）", "Download Certificate (PDF)")}</span>
              </button>
            </div>
          </div>
        )}

        <OpenNoteAlert note={openNote} />
      </div>
    </section>
  );
}

function ChecklistCard() {
  const { tx, lang } = useI18n();
  const { regwebAvailable } = useAuth();
  const [data, setData] = useState<RegistrationChecklist | null>(null);
  const [loading, setLoading] = useState(regwebAvailable);
  const [errorText, setErrorText] = useState<string | null>(null);

  useEffect(() => {
    if (!regwebAvailable) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    fetchRegistrationChecklist()
      .then((body) => {
        if (!cancelled) setData(body);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setErrorText(
          cardErrorText(
            err,
            tx,
            "無法讀取註冊事項，請稍後再試",
            "Couldn't load your registration checklist. Please try again shortly",
          ),
        );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [regwebAvailable, tx]);

  const hasOutUrl = data !== null && data.items.some((item) => item.out_url !== null);
  const totalCount = data ? data.items.length : 0;
  const completedCount = data
    ? data.items.filter((it) => checklistStatusTone(it.status_text) === "success").length
    : 0;
  const completionPercent = totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0;

  return (
    <section className="profile-card" aria-label={tx("註冊事項", "Registration Checklist")}>
      <div className="profile-card-header">
        <div className="d-flex align-items-center gap-2.5 min-w-0 flex-grow-1">
          <CardIcon>
            <CardChecklist size={18} />
          </CardIcon>
          <div className="min-w-0">
            <h2 className="h6 fw-bold mb-0 text-dark text-truncate">{tx("註冊事項", "Registration Checklist")}</h2>
            <span className="text-muted text-truncate d-block" style={{ fontSize: "0.78rem" }}>
              {tx(
                "網路註冊系統之註冊程序辦理狀態",
                "Registration steps, live from the campus registration system",
              )}
            </span>
          </div>
        </div>

        {totalCount > 0 && (
          <div className="card-header-actions">
            <span className="studio-badge studio-badge-secondary d-inline-flex align-items-center">
              <CheckCircleFill size={12} className="text-teal-600 me-1.5 flex-shrink-0" />
              <span>
                {tx(
                  `已完成 ${completedCount} / ${totalCount} 項 (${completionPercent}%)`,
                  `${completedCount} / ${totalCount} completed (${completionPercent}%)`,
                )}
              </span>
            </span>
          </div>
        )}
      </div>

      <div className="profile-card-body">
        {errorText !== null && <CardErrorLine text={errorText} />}

        {!regwebAvailable ? (
          <FeatureOffNote />
        ) : loading && data === null ? (
          <div className="p-4 text-center text-muted bg-light rounded-3">
            <div className="spinner-border spinner-border-sm text-teal-600 me-2" role="status" aria-hidden />
            <span className="fw-semibold">{tx("讀取註冊事項中…", "Loading registration checklist…")}</span>
          </div>
        ) : data === null ? null : (
          <>
            {totalCount > 0 && (
              <div className="mb-3">
                <div
                  className="checklist-progress-bar-track mt-0"
                  role="progressbar"
                  aria-valuenow={completionPercent}
                  aria-valuemin={0}
                  aria-valuemax={100}
                >
                  <div
                    className="checklist-progress-bar-fill"
                    style={{ width: `${completionPercent}%` }}
                  />
                </div>
              </div>
            )}

            {data.items.length === 0 ? (
              <p className="text-muted small mb-0 p-3 text-center bg-light rounded-3">
                {tx("目前無註冊事項資料", "No registration items right now")}
              </p>
            ) : (
              <div className="checklist-items-grid">
                {data.items.map((item, index) => {
                  const titleParts = splitBilingualText(item.title);
                  const isEn = lang === "en";
                  const titlePrimary = isEn && titleParts.en ? titleParts.en : titleParts.zh;
                  const titleSecondary = isEn
                    ? (titleParts.en ? titleParts.zh : "")
                    : titleParts.en;
                  const status = formatChecklistStatus(item.status_text, lang);
                  const cleanPeriod = sanitizeChecklistPeriod(item.title, item.period, lang);

                  let cardStatusClass = "is-secondary";
                  if (status.tone === "success") cardStatusClass = "is-completed";
                  else if (status.tone === "warning") cardStatusClass = "is-warning";

                  return (
                    <a
                      href={item.out_url ?? "#"}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="checklist-item-card-link"
                    >
                      <div
                        key={`${item.title}-${index}`}
                        className={`checklist-item-card ${cardStatusClass}`}
                      >
                      <div className="d-flex align-items-start justify-content-between gap-2.5">
                        <div className="d-flex align-items-baseline gap-2 min-w-0 flex-grow-1">
                          <span className="checklist-item-index">
                            {String(index + 1).padStart(2, "0")}
                          </span>
                          <div className="min-w-0 flex-grow-1">
                            <div className="checklist-item-title">
                              {titlePrimary}
                            </div>
                            {titleSecondary !== "" && (
                              <div className="checklist-item-subtitle">
                                {titleSecondary}
                              </div>
                            )}
                          </div>
                        </div>

                        <span
                          className={`studio-badge studio-badge-${status.tone} flex-shrink-0`}
                          style={{ whiteSpace: "nowrap" }}
                        >
                          {status.label}
                        </span>
                      </div>

                      {cleanPeriod !== "" && (
                        <div className="d-flex align-items-center mt-1 pt-1">
                          <span className="checklist-item-period-pill text-truncate">
                            <Clock size={11} className="text-teal-600 flex-shrink-0" />
                            <span className="text-truncate">{cleanPeriod}</span>
                          </span>
                        </div>
                      )}
                    </div></a>
                  );
                })}
              </div>
            )}

            {hasOutUrl && (
              <p className="text-muted mt-3 mb-0" style={{ fontSize: "0.74rem" }}>
                {tx(
                  "連結僅供參考（於校內系統開啟）",
                  "Links are for reference only (they open inside the campus system)",
                )}
              </p>
            )}
            {!data.enrollcert_present && (
              <p className="text-muted mt-2 mb-0" style={{ fontSize: "0.74rem" }}>
                {tx("校方尚未開放在學證明", "The school hasn't opened this term's enrollment certificate yet")}
              </p>
            )}
          </>
        )}
      </div>
    </section>
  );
}

type ProfileTab = "all" | "grades" | "payment" | "registration" | "cert";

function MePage() {
  const { tx } = useI18n();
  const {
    status,
    studentNo,
    scoAvailable,
    regwebAvailable,
    featureStuEnroll,
    requireRelogin,
  } = useAuth();
  const [activeTab, setActiveTab] = useState<ProfileTab>("all");

  // Zombie session detector: logged in but the stu_enroll fan-out never
  // connected (session predates the feature flip) -> full re-login.
  useEffect(() => {
    if (shouldForceRelogin(status, featureStuEnroll, regwebAvailable, scoAvailable)) {
      requireRelogin();
    }
  }, [status, featureStuEnroll, regwebAvailable, scoAvailable, requireRelogin]);

  return (
    <div className="profile-page-container py-2 py-sm-3">
      {/* Hero Header Card */}
      <div className="records-hero-card profile-hero-card">
        <div className="d-flex align-items-center justify-content-between flex-wrap" style={{ gap: "1rem" }}>
          <div>
            <h1 className="h4 fw-bold mb-2 text-dark d-flex align-items-center" style={{ gap: "0.85rem" }}>
              <div
                className="p-2 rounded-3 bg-teal-50 text-teal-700 d-inline-flex align-items-center justify-content-center flex-shrink-0"
                style={{ width: "42px", height: "42px" }}
              >
                <PersonCircle size={22} />
              </div>
              <span>{tx("我的資料", "My Profile")}</span>
            </h1>
            <p className="text-muted mb-0" style={{ fontSize: "0.88rem", lineHeight: 1.5 }}>
              {tx(
                "歷年成績、繳費狀態與註冊/在學證明，皆由校內系統資料即時產生。",
                "Your academic transcript, tuition billing records, registration items, and enrollment certificate — generated live from campus systems.",
              )}
            </p>
          </div>
        </div>

        {/* Profile Info Summary Chips (Compact & without ephemeral storage note) */}
        <div className="profile-info-chips-row">
          {studentNo && (
            <div className="profile-badge-chip">
              <PersonBadge size={14} className="text-teal-600" />
              <span className="text-muted">{tx("學號：", "ID: ")}</span>
              <strong className="font-monospace text-dark">{studentNo}</strong>
            </div>
          )}

          <div className="profile-badge-chip">
            <span className={`status-indicator-dot ${scoAvailable ? "online" : "offline"}`} />
            <span className="text-muted">{tx("歷年成績：", "Grades: ")}</span>
            <span className={scoAvailable ? "text-emerald-700 fw-bold" : "text-slate-500"}>
              {scoAvailable ? tx("已連線", "Connected") : tx("未開通", "Offline")}
            </span>
          </div>

          <div className="profile-badge-chip">
            <span className={`status-indicator-dot ${regwebAvailable ? "online" : "offline"}`} />
            <span className="text-muted">{tx("教務/繳費：", "Billing: ")}</span>
            <span className={regwebAvailable ? "text-emerald-700 fw-bold" : "text-slate-500"}>
              {regwebAvailable ? tx("已連線", "Connected") : tx("未開通", "Offline")}
            </span>
          </div>
        </div>
      </div>

      {/* Filter Tabs (4-Segmented Control) */}
      <div className="profile-nav-tabs-wrapper">
        <div className="record-filter-nav profile-nav-tabs" role="tablist" aria-label={tx("資料切換", "Profile tabs")}>
          <button
            type="button"
            className={`record-filter-btn ${activeTab === "all" ? "active" : ""}`}
            onClick={() => setActiveTab("all")}
          >
            <span>{tx("全部", "All")}</span>
          </button>
          <button
            type="button"
            className={`record-filter-btn ${activeTab === "grades" ? "active" : ""}`}
            onClick={() => setActiveTab("grades")}
          >
            <Mortarboard size={14} />
            <span>{tx("歷年成績", "Grades")}</span>
          </button>
          <button
            type="button"
            className={`record-filter-btn ${activeTab === "payment" ? "active" : ""}`}
            onClick={() => setActiveTab("payment")}
          >
            <CashStack size={14} />
            <span>{tx("繳費狀態", "Payment")}</span>
          </button>
          <button
            type="button"
            className={`record-filter-btn ${activeTab === "registration" || activeTab === "cert" ? "active" : ""}`}
            onClick={() => setActiveTab("registration")}
          >
            <Award size={14} />
            <span>{tx("註冊與在學證明", "Registration & Cert")}</span>
          </button>
        </div>
      </div>

      {/* Profile Cards Content */}
      <div className="d-flex flex-column" style={{ gap: "0.5rem" }}>
        {(activeTab === "all" || activeTab === "grades") && <GradesCard />}
        {(activeTab === "all" || activeTab === "payment") && <PaymentCard />}
        {(activeTab === "all" || activeTab === "registration" || activeTab === "cert") && (
          <>
            <CertCard />
            <ChecklistCard />
          </>
        )}
      </div>
    </div>
  );
}

export default MePage;
