import { useCallback, useEffect, useState } from "react";
import { ArrowRepeat, BookmarkCheck } from "react-bootstrap-icons";

import { ApiError, fetchSelections, syncSelections } from "../lib/api";
import type { SelectionItem } from "../lib/api";

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
    item.credit !== null ? `${item.credit} 學分` : null,
    item.compulsory_elective !== "" ? item.compulsory_elective : null,
    item.teacher,
  ]
    .filter((part) => part !== null && part !== "")
    .join(" · ");
  const where = [item.times, item.room ?? item.room_text]
    .filter((part) => part !== null && part !== "")
    .join(" ");

  return (
    <div className="selection-card" data-state={item.state}>
      <div className="d-flex justify-content-between align-items-start gap-2">
        <div>
          <div className="d-flex align-items-center gap-1.5 flex-wrap">
            <span className="fw-bold text-dark">{item.name}</span>
            {item.unknown && (
              <span className="badge text-bg-secondary" style={{ fontSize: "0.7rem" }}>
                目錄查無此課
              </span>
            )}
          </div>
          {meta !== "" && <div className="text-muted small mt-0.5">{meta}</div>}
          {where !== "" && <div className="text-muted small">{where}</div>}
        </div>
        <span className={`badge ${badgeClass(item.state)} px-2.5 py-1 rounded-pill`} style={{ fontSize: "0.75rem" }}>
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
  const [errorText, setErrorText] = useState<string | null>(null);

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
        // 401s are handled by the global seam (redirect); anything else -> inline
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
        // 401 -> global seam redirects
      })
      .finally(() => setSyncing(false));
  }, [syncing]);

  const groups = STATE_ORDER.map((state) => ({
    state,
    rows: items.filter((item) => item.state === state),
  })).filter((group) => group.rows.length > 0);
  const extraStates = [
    ...new Set(items.map((item) => item.state)),
  ].filter((state) => !STATE_ORDER.includes(state));
  for (const state of extraStates) {
    groups.push({ state, rows: items.filter((item) => item.state === state) });
  }

  return (
    <div className="row justify-content-center">
      <div className="col-12 col-lg-9">
        <div className="card shadow-sm border-0 rounded-4">
          <div className="card-body p-4">
            <div className="d-flex align-items-center justify-content-between flex-wrap gap-2 mb-3">
              <div>
                <h2 className="h5 fw-bold mb-0 text-dark d-flex align-items-center gap-2">
                  <BookmarkCheck className="text-teal-600" size={20} />
                  <span>我的已選課程</span>
                </h2>
                <div className="text-muted small mt-1" role="status">
                  {syncedAt === null ? (
                    "尚未同步。按下「同步我的已選」從學校系統讀取最新狀態。"
                  ) : (
                    <>上次同步：{syncedAt}</>
                  )}
                  {diff !== null && (
                    <span className="ms-2 badge text-bg-light border" data-testid="sync-diff">
                      新增 {diff.added} · 移除 {diff.removed} · 未變 {diff.unchanged}
                    </span>
                  )}
                </div>
              </div>
              <button
                type="button"
                className="btn btn-brand d-inline-flex align-items-center gap-1.5 shadow-sm"
                onClick={onSync}
                disabled={syncing}
              >
                <ArrowRepeat className={syncing ? "spinner-border spinner-border-sm" : ""} size={14} />
                <span>{syncing ? "同步中…" : "同步我的已選"}</span>
              </button>
            </div>

            {errorText !== null && (
              <div className="alert alert-warning py-2 px-3 small rounded-3 mb-3" role="alert">
                {errorText}
              </div>
            )}

            {loading ? (
              <p className="text-muted small mb-0 p-4 text-center bg-light rounded-3">讀取中…</p>
            ) : syncedAt === null ? null : items.length === 0 ? (
              <p className="text-muted small mb-0 p-4 text-center bg-light rounded-3">學校系統目前無任何已選紀錄。</p>
            ) : (
              groups.map((group) => (
                <section key={group.state} className="mb-3.5">
                  <div className="d-flex align-items-center gap-2 mb-2">
                    <span className="fw-bold text-dark small" style={{ fontSize: "0.88rem" }}>
                      {group.state}
                    </span>
                    <span className="badge text-bg-light border rounded-pill font-monospace">
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
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export default SelectedPage;

