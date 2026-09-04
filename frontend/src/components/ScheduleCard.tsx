/**
 * 選課日程 widget (anonymous; GET /api/schedule).
 *
 * Compact full-width strip above the console: current window + countdown,
 * next stage, and the school's complete schedule behind a toggle. Date
 * formatting is manual (M/D + HH:mm pinned to the school's own Asia/Taipei
 * stamps) so it never depends on the viewer's locale. Data is fetched once
 * per mount - the school page moves once a term; the countdown text itself
 * re-derives every 30s and flips active/next boundaries without a refetch.
 *
 * Renders nothing (null) while loading, on fetch failure, or when the API
 * reports ok=false: an informational widget must never become an error.
 */

import { useEffect, useMemo, useState } from "react";
import { CalendarEvent, ChevronDown, ChevronUp, ClockHistory } from "react-bootstrap-icons";

import { fetchSchedule } from "../lib/api";
import type { ScheduleResponse } from "../lib/api";
import {
  deriveScheduleState,
  eventLabel,
  formatCountdown,
} from "../lib/schedule";
import type { RowState } from "../lib/schedule";
import { useI18n } from "../lib/i18n";

const TICK_MS = 30_000;

function fmtStamp(date: Date, lang: "zh" | "en"): string {
  const hh = String(date.getHours()).padStart(2, "0");
  const mm = String(date.getMinutes()).padStart(2, "0");
  if (lang === "en") {
    const months = [
      "Jan", "Feb", "Mar", "Apr", "May", "Jun",
      "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ];
    return `${months[date.getMonth()]} ${date.getDate()}, ${hh}:${mm}`;
  }
  return `${date.getMonth() + 1}/${date.getDate()} ${hh}:${mm}`;
}

const STATE_PILL: Record<RowState, string> = {
  done: "bg-slate-100 text-slate-500 border",
  active: "bg-emerald-100 text-emerald-800 border border-emerald-300",
  upcoming: "bg-secondary-subtle text-secondary border",
};

export function ScheduleCard() {
  const { lang, tx } = useI18n();
  const [data, setData] = useState<ScheduleResponse | null>(null);
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState(false);
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const abort = new AbortController();
    fetchSchedule(abort.signal)
      .then((body) => setData(body))
      .catch((err: unknown) => {
        if (!(err instanceof DOMException && err.name === "AbortError")) setFailed(true);
      });
    return () => abort.abort();
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), TICK_MS);
    return () => window.clearInterval(timer);
  }, []);

  const derived = useMemo(
    () => deriveScheduleState(data?.events ?? [], now),
    [data, now],
  );

  if (failed || data === null || !data.ok || derived.rows.length === 0) return null;

  const stateText = (state: RowState): string =>
    state === "active"
      ? tx("進行中", "Now")
      : state === "done"
        ? tx("已結束", "Ended")
        : tx("未開始", "Upcoming");

  let summary: string;
  if (derived.active !== null && derived.active.end !== null) {
    const countdown = formatCountdown(derived.active.end.getTime() - now.getTime(), lang);
    summary = tx(
      `${eventLabel(derived.active.event, "zh")}進行中，剩 ${countdown} 結束`,
      `${eventLabel(derived.active.event, "en")} is on now, ends in ${countdown}`,
    );
  } else if (derived.next !== null) {
    const countdown = formatCountdown(derived.next.at.getTime() - now.getTime(), lang);
    const label = eventLabel(derived.next.event, lang);
    const stamp = fmtStamp(derived.next.at, lang);
    summary =
      derived.next.kind === "instant"
        ? tx(`下一節點：${label} ${stamp} 公佈（${countdown} 後）`, `Next: ${label} announced ${stamp} (in ${countdown})`)
        : tx(`下一階段：${label} ${stamp} 開始（${countdown} 後）`, `Next: ${label} starts ${stamp} (in ${countdown})`);
  } else {
    summary = tx("本學期選課日程已全部結束", "All selection windows for this semester have ended");
  }

  return (
    <div className="col-12">
      <div className="bg-white rounded-3 border shadow-sm px-3 py-2">
        <div className="d-flex align-items-center justify-content-between flex-wrap" style={{ gap: "0.5rem" }}>
          <div className="d-flex align-items-center flex-wrap small" style={{ gap: "0.45rem" }}>
            <CalendarEvent size={14} className="text-teal-600" />
            <span className="fw-bold text-dark">
              {lang === "zh" ? data.title : tx("選課日程", "Course-selection schedule")}
            </span>
            {data.stale && (
              <span className="d-inline-flex align-items-center px-2 py-0 bg-amber-100 text-amber-800 border border-amber-300 rounded-pill" style={{ fontSize: "0.72rem" }} title={data.fetched_at ?? undefined}>
                <ClockHistory size={10} className="me-1" />
                {tx("快照", "Snapshot")}
              </span>
            )}
            <span className="text-muted">{summary}</span>
          </div>
          <button
            type="button"
            className="btn btn-sm btn-outline-secondary rounded-pill d-inline-flex align-items-center gap-1 px-2.5 py-0.5"
            onClick={() => setOpen((prev) => !prev)}
            aria-expanded={open}
            title={open ? tx("收合完整日程", "Collapse full schedule") : tx("展開完整日程", "Show full schedule")}
          >
            {open ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            <span style={{ fontSize: "0.78rem" }}>{open ? tx("收合", "Less") : tx("完整日程", "Full schedule")}</span>
          </button>
        </div>
        {open && (
          <ul className="list-unstyled mb-0 mt-2 small border-top pt-2">
            {derived.rows.map((row) => (
              <li
                key={row.event.key}
                className={`d-flex align-items-center flex-wrap py-1 ${row.state === "done" ? "text-black-50" : ""}`}
                style={{ gap: "0.5rem" }}
              >
                <span className={`d-inline-flex align-items-center px-2 py-0 rounded-pill ${STATE_PILL[row.state]}`} style={{ fontSize: "0.72rem", minWidth: "3.4rem", justifyContent: "center" }}>
                  {stateText(row.state)}
                </span>
                <span className={`fw-semibold ${row.state === "done" ? "" : "text-dark"}`}>
                  {eventLabel(row.event, lang)}
                </span>
                <span className="text-muted">
                  {row.event.kind === "window" && row.end !== null
                    ? `${fmtStamp(row.start, lang)} – ${fmtStamp(row.end, lang)}`
                    : fmtStamp(row.start, lang)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
