/**
 * Degrade banner (plan todo 10): polls /api/catalog/meta; if the catalog
 * ingest reports failure (ok=false) or the request itself fails, show a
 * visible "last successful snapshot" notice. The rest of the page stays
 * fully usable — this is read-only degrade posture, not an outage page.
 */

import { useEffect, useState } from "react";

import { fetchCatalogMeta } from "../lib/api";

const POLL_INTERVAL_MS = 60_000;

interface MetaState {
  degraded: boolean;
  /** Last known snapshot timestamp (from meta.updated_at, any state). */
  updatedAt: string | null;
}

function formatSnapshotTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso;
  }
  return date.toLocaleString("zh-TW", {
    timeZone: "Asia/Taipei",
    hour12: false,
  });
}

function DegradeBanner() {
  const [state, setState] = useState<MetaState>({
    degraded: false,
    updatedAt: null,
  });

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    const poll = async () => {
      try {
        const meta = await fetchCatalogMeta(controller.signal);
        if (cancelled) return;
        setState({
          degraded: !meta.ok,
          updatedAt: meta.updated_at ?? null,
        });
      } catch (error) {
        if (cancelled || controller.signal.aborted) return;
        console.warn("catalog meta fetch failed:", error);
        setState((prev) => ({ ...prev, degraded: true }));
      }
    };

    void poll();
    const timer = window.setInterval(() => void poll(), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(timer);
    };
  }, []);

  if (!state.degraded) {
    return null;
  }

  const message =
    state.updatedAt !== null
      ? `課程資料為 ${formatSnapshotTime(state.updatedAt)} 更新（學校目錄暫時無法同步）`
      : "課程資料更新時間未知（學校目錄暫時無法同步）";

  return (
    <div
      className="alert alert-warning text-center mb-0 rounded-0"
      role="alert"
      data-testid="degrade-banner"
    >
      {message}
    </div>
  );
}

export default DegradeBanner;
