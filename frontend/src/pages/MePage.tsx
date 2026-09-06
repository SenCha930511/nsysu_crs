/**
 * /me → 我的 (personal records): 歷年成績 (SCO family), 繳費狀態 and 在學證明
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
  CashStack,
  Download,
  ExclamationCircleFill,
  FileEarmarkPdf,
  InfoCircleFill,
  Mortarboard,
  MortarboardFill,
  PersonCircle,
} from "react-bootstrap-icons";

import { fetchGrades, fetchPaymentStatus, syncGrades } from "../lib/api";
import type {
  GradesResponse,
  PaymentStatusResponse,
} from "../lib/api";
import { useI18n } from "../lib/i18n";
import { meFeatureErrorKind } from "../lib/meErrors";
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
    <div className="d-flex align-items-start gap-2 text-muted small bg-light rounded-3 p-3">
      <InfoCircleFill size={15} className="flex-shrink-0 mt-0.5 text-slate-400" />
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
    <div className="alert alert-warning py-1.5 px-3 small rounded-3 mb-3" role="alert">
      <ExclamationCircleFill size={14} className="me-1.5" />
      {text}
    </div>
  );
}

function CardIcon({ children }: { children: ReactNode }) {
  return (
    <span className="p-2 rounded-3 bg-teal-50 text-teal-700 d-inline-flex align-items-center justify-content-center">
      {children}
    </span>
  );
}

function GradesCard() {
  const { tx } = useI18n();
  const { scoAvailable } = useAuth();
  const [data, setData] = useState<GradesResponse | null>(null);
  const [loading, setLoading] = useState(scoAvailable);
  const [syncing, setSyncing] = useState(false);
  const [errorText, setErrorText] = useState<string | null>(null);

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
    syncGrades()
      .then((body) => {
        // The sync response's added/removed/unchanged diff stays unrendered:
        // only the fresh snapshot drives the view (per the M3 card spec).
        setData({ synced_at: body.synced_at, items: body.items });
      })
      .catch((err: unknown) => {
        setErrorText(
          cardErrorText(err, tx, "同步失敗，請稍後再試", "Sync failed. Please try again shortly"),
        );
      })
      .finally(() => setSyncing(false));
  }, [syncing, scoAvailable, tx]);

  return (
    <section className="card shadow-sm border-0 rounded-4" aria-label={tx("歷年成績", "Grades")}>
      <div className="card-body p-4">
        <div className="d-flex align-items-center justify-content-between flex-wrap" style={{ gap: "0.75rem" }}>
          <h2 className="h6 fw-bold mb-0 text-dark d-flex align-items-center" style={{ gap: "0.6rem" }}>
            <CardIcon>
              <MortarboardFill size={16} />
            </CardIcon>
            <span>{tx("歷年成績", "Grades")}</span>
          </h2>
          {scoAvailable && (
            <div className="d-flex align-items-center flex-wrap" style={{ gap: "0.75rem" }}>
              <span className="text-muted d-none d-sm-inline" style={{ fontSize: "0.78rem" }} role="status">
                {data?.synced_at
                  ? tx(`上次同步：${formatDateTime(data.synced_at)}`, `Last synced: ${formatDateTime(data.synced_at)}`)
                  : tx("尚未同步", "Not synced yet")}
              </span>
              <button
                type="button"
                className="btn btn-sm btn-brand rounded-pill px-3 d-inline-flex align-items-center fw-semibold"
                style={{ gap: "0.45rem" }}
                onClick={onSync}
                disabled={syncing}
                data-testid="grades-sync"
              >
                {syncing ? (
                  <span className="spinner-border spinner-border-sm" aria-hidden />
                ) : (
                  <ArrowRepeat size={13} />
                )}
                <span>{syncing ? tx("同步中…", "Syncing…") : tx("同步歷年成績", "Sync grades")}</span>
              </button>
            </div>
          )}
        </div>

        <div className="mt-3">
          {errorText !== null && <CardErrorLine text={errorText} />}

          {!scoAvailable ? (
            <FeatureOffNote />
          ) : loading && data === null ? (
            <p className="text-muted small mb-0 p-3 text-center bg-light rounded-3">
              <span className="spinner-border spinner-border-sm me-2" aria-hidden />
              {tx("讀取中…", "Loading…")}
            </p>
          ) : data === null ? null : data.items.length === 0 ? (
            <div className="text-center text-muted py-4">
              <div className="p-3 bg-slate-100 text-slate-400 rounded-circle d-inline-flex align-items-center justify-content-center mx-auto mb-3" style={{ width: "64px", height: "64px" }}>
                <Mortarboard size={28} />
              </div>
              <h3 className="h6 fw-bold text-dark mb-1">{tx("尚無成績資料", "No grade records yet")}</h3>
              <p className="small mb-3" style={{ maxWidth: "26rem", margin: "0 auto" }}>
                {tx(
                  "按下「同步歷年成績」即可從學校教務系統讀取你的歷年成績。",
                  "Hit “Sync grades” to pull your full grade history from the school system.",
                )}
              </p>
              <button
                type="button"
                className="btn btn-sm btn-outline-brand rounded-pill px-3.5 py-1.5 fw-semibold d-inline-flex align-items-center gap-1.5"
                onClick={onSync}
                disabled={syncing}
              >
                {syncing ? (
                  <span className="spinner-border spinner-border-sm" aria-hidden />
                ) : (
                  <ArrowRepeat size={14} />
                )}
                <span>{syncing ? tx("同步中…", "Syncing…") : tx("同步歷年成績", "Sync grades")}</span>
              </button>
            </div>
          ) : (
            // Rows render VERBATIM (string[][]); any header row is just
            // items[0]. Column names / GPA math ship only after a later data
            // round pins the school's row format - do not invent them here.
            <div className="table-responsive">
              <table className="table table-sm mb-0">
                <tbody>
                  {data.items.map((row, rowIndex) => (
                    // Verbatim rows are never reordered, so index keys are safe.
                    <tr key={rowIndex}>
                      {row.map((cell, cellIndex) => (
                        <td key={cellIndex}>{cell}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
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
    <section className="card shadow-sm border-0 rounded-4" aria-label={tx("繳費狀態", "Payment")}>
      <div className="card-body p-4">
        <div className="d-flex align-items-center justify-content-between flex-wrap" style={{ gap: "0.75rem" }}>
          <h2 className="h6 fw-bold mb-0 text-dark d-flex align-items-center" style={{ gap: "0.6rem" }}>
            <CardIcon>
              <CashStack size={16} />
            </CardIcon>
            <span>{tx("繳費狀態", "Payment")}</span>
          </h2>
          {data !== null && data.dept !== "" && (
            <span className="text-muted small">
              {tx("系所：", "Department: ")}{data.dept}
            </span>
          )}
        </div>

        <div className="mt-3">
          {errorText !== null && <CardErrorLine text={errorText} />}

          {!regwebAvailable ? (
            <FeatureOffNote />
          ) : loading && data === null ? (
            <p className="text-muted small mb-0 p-3 text-center bg-light rounded-3">
              <span className="spinner-border spinner-border-sm me-2" aria-hidden />
              {tx("讀取中…", "Loading…")}
            </p>
          ) : data === null ? null : data.bills.length === 0 ? (
            <p className="text-muted small mb-0 p-3 text-center bg-light rounded-3">
              {tx("目前沒有任何繳費單據", "No bills on record right now")}
            </p>
          ) : (
            <div className="table-responsive">
              <table className="table table-sm mb-0 align-middle">
                <thead>
                  <tr>
                    <th scope="col">{tx("單據名稱", "Bill")}</th>
                    <th scope="col">{tx("應繳金額", "Amount")}</th>
                    <th scope="col">{tx("繳費狀態", "Status")}</th>
                    <th scope="col">{tx("繳費日期", "Pay date")}</th>
                    <th scope="col">{tx("收據", "Receipt")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.bills.map((bill, index) => {
                    const paid = bill.pay_date !== null && bill.pay_date !== "";
                    return (
                      <tr key={`${bill.item}-${index}`}>
                        <td>{bill.item}</td>
                        <td>{bill.amount}</td>
                        <td>
                          <span className={`studio-badge ${paid ? "studio-badge-success" : "studio-badge-secondary"}`}>
                            {bill.status}
                          </span>
                        </td>
                        <td>{bill.pay_date !== null && bill.pay_date !== "" ? bill.pay_date : "—"}</td>
                        <td className="text-muted small">
                          {bill.receipt_available ? tx("收據已開立", "Receipt issued") : "—"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

function CertCard() {
  const { tx } = useI18n();
  const { regwebAvailable } = useAuth();
  const [openNote, setOpenNote] = useState<string | null>(null);

  // window.open reports nothing about the HTTP result (PDF or error body),
  // so the only pre-emptible failure is the flag-false case, handled above;
  // the click note covers "nothing visibly happened" UX on the browser side.
  const onDownload = () => {
    window.open("/api/me/enrollment-cert", "_blank");
    setOpenNote(
      tx(
        "檔案已在新分頁開啟下載；若沒有反應，請允許瀏覽器的彈出式視窗後再試一次。",
        "The file downloads in a new tab. If nothing happened, allow pop-ups for this site and try again.",
      ),
    );
  };

  return (
    <section className="card shadow-sm border-0 rounded-4" aria-label={tx("在學證明", "Enrollment Certificate")}>
      <div className="card-body p-4">
        <h2 className="h6 fw-bold mb-0 text-dark d-flex align-items-center" style={{ gap: "0.6rem" }}>
          <CardIcon>
            <FileEarmarkPdf size={16} />
          </CardIcon>
          <span>{tx("在學證明", "Enrollment Certificate")}</span>
        </h2>

        <p className="text-muted small mt-3 mb-3" style={{ lineHeight: 1.6 }}>
          {tx(
            "由教務處線上系統即時產出的在學證明（PDF），下載內容不經本網站保存。",
            "A certificate-of-enrollment PDF generated live by the school's registration system; the file is never stored on this site.",
          )}
        </p>

        {!regwebAvailable ? (
          <FeatureOffNote />
        ) : (
          <div className="d-flex flex-column align-items-start" style={{ gap: "0.5rem" }}>
            <button
              type="button"
              className="btn btn-brand rounded-pill px-4 py-2 d-inline-flex align-items-center shadow-sm fw-semibold"
              style={{ fontSize: "0.88rem", gap: "0.6rem" }}
              onClick={onDownload}
              data-testid="cert-download"
            >
              <Download size={15} />
              <span>{tx("下載在學證明（PDF）", "Download Certificate of Enrollment (PDF)")}</span>
            </button>
            {openNote !== null && (
              <p className="text-muted small mb-0" role="status">{openNote}</p>
            )}
          </div>
        )}
      </div>
    </section>
  );
}

function MePage() {
  const { tx } = useI18n();
  return (
    <div className="py-3" style={{ maxWidth: "880px", margin: "0 auto" }}>
      <div className="mb-3">
        <h1 className="h4 fw-bold mb-2 text-dark d-flex align-items-center" style={{ gap: "0.85rem" }}>
          <div className="p-2 rounded-3 bg-teal-50 text-teal-700 d-inline-flex align-items-center justify-content-center" style={{ width: "42px", height: "42px" }}>
            <PersonCircle size={22} />
          </div>
          <span>{tx("我的專區", "My Records")}</span>
        </h1>
        <p className="text-muted mb-0" style={{ fontSize: "0.9rem", lineHeight: 1.6 }}>
          {tx(
            "歷年成績、繳費狀態與在學證明，皆由校內系統資料即時產生。",
            "Your grades, billing status, and enrollment certificate — generated live from the campus systems.",
          )}
        </p>
      </div>

      <div className="d-flex flex-column" style={{ gap: "1rem" }}>
        <GradesCard />
        <PaymentCard />
        <CertCard />
      </div>
    </div>
  );
}

export default MePage;
