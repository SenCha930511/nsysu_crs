/**
 * /selected: my real selections from the school system.
 *
 * - Boot: GET /api/me/selections (cached snapshot; "尚未同步" when never).
 * - 同步我的已選: POST /api/me/selections/sync -> synced_at + diff counts
 *   (added/removed/unchanged) + the list grouped by 選上/登記加選/失敗 with
 *   state badges; cards are quota-agnostic (the sync payload carries no
 *   quota fields by design).
 * - A dead school jar answers 401 SELCRS_EXPIRED; the global 401 seam turns
 *   that into soft logout + /login?reason=expired. School-down answers 503
 *   and shows the degrade text inline, previous snapshot untouched.
 */

import { useCallback, useEffect, useState } from "react";
import { ArrowRepeat } from "react-bootstrap-icons";

import { ApiError, fetchSelections, syncSelections } from "../lib/api";
import type { SelectionItem } from "../lib/api";

const STATE_ORDER = ["選上", "登記加選", "失敗"];
const STATE_BADGE: Record<string, string> = {
  選上: "text-bg-success",
  登記加選: "text-bg-info",
  失敗: "text-bg-danger",
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
          <span className="fw-semibold">{item.name}</span>
          {item.unknown && (
            <span className="badge text-bg-secondary ms-1">目錄查無此課</span>
          )}
          {meta !== "" && <div className="text-muted small">{meta}</div>}
          {where !== "" && <div className="text-muted small">{where}</div>}
        </div>
        <span className={`badge ${badgeClass(item.state)}`}>{item.state}</span>
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
        <div className="card">
          <div className="card-body">
            <div className="d-flex align-items-center justify-content-between flex-wrap gap-2">
              <h2 className="h6 fw-bold mb-0">我的已選</h2>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={onSync}
                disabled={syncing}
              >
                <ArrowRepeat className="me-1" />
                {syncing ? "同步中…" : "同步我的已選"}
              </button>
            </div>

            <p className="text-muted small mt-2 mb-2" role="status">
              {syncedAt === null ? (
                "尚未同步。按下「同步我的已選」從學校系統讀取最新狀態。"
              ) : (
                <>上次同步：{syncedAt}</>
              )}
              {diff !== null && (
                <span className="ms-2" data-testid="sync-diff">
                  （新增 {diff.added}｜移除 {diff.removed}｜未變 {diff.unchanged}）
                </span>
              )}
            </p>

            {errorText !== null && (
              <div className="alert alert-warning py-2 small" role="alert">
                {errorText}
              </div>
            )}

            {loading ? (
              <p className="text-muted small mb-0">讀取中…</p>
            ) : syncedAt === null ? null : items.length === 0 ? (
              <p className="text-muted small mb-0">學校系統目前無任何已選紀錄。</p>
            ) : (
              groups.map((group) => (
                <section key={group.state} className="mb-3">
                  <h3 className="h6 small text-muted mb-1">
                    <span className={`badge ${badgeClass(group.state)} me-1`}>
                      {group.state}
                    </span>
                    {group.rows.length} 門
                  </h3>
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
