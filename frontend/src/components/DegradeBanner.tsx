/**
 * Degrade banner (todo 10 + todo 17): polls /api/catalog/meta (stale-catalog
 * notice) AND /api/ops/state (breaker read-only posture notice) and renders a
 * stacked alert per active notice. The rest of the page stays fully usable —
 * this is the degraded posture surface, not an outage page. The mapping
 * itself is pure and vitest-pinned in lib/degrade.ts.
 */

import { useEffect, useRef, useState } from "react";

import { fetchCatalogMeta, fetchOpsState, type CatalogMeta } from "../lib/api";
import { bannerNotices, type BannerNotice } from "../lib/degrade";

const POLL_INTERVAL_MS = 60_000;

function DegradeBanner() {
  const [notices, setNotices] = useState<BannerNotice[]>([]);
  const lastMetaRef = useRef<CatalogMeta | null>(null);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    const poll = async () => {
      const [metaResult, opsResult] = await Promise.allSettled([
        fetchCatalogMeta(controller.signal),
        fetchOpsState(controller.signal),
      ]);
      if (cancelled || controller.signal.aborted) return;
      if (metaResult.status === "fulfilled") {
        lastMetaRef.current = metaResult.value;
      } else {
        console.warn("catalog meta fetch failed:", metaResult.reason);
      }
      if (opsResult.status === "rejected") {
        console.warn("ops state fetch failed:", opsResult.reason);
      }
      const ops = opsResult.status === "fulfilled" ? opsResult.value : null;
      setNotices(
        bannerNotices(lastMetaRef.current, metaResult.status === "rejected", ops),
      );
    };

    void poll();
    const timer = window.setInterval(() => void poll(), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(timer);
    };
  }, []);

  if (notices.length === 0) {
    return null;
  }

  return (
    <div data-testid="degrade-banner">
      {notices.map((notice) => (
        <div
          key={notice.kind}
          className={`alert ${
            notice.kind === "breaker" ? "alert-danger" : "alert-warning"
          } text-center mb-0 rounded-0`}
          role="alert"
          data-testid={notice.testId}
        >
          {notice.message}
        </div>
      ))}
    </div>
  );
}

export default DegradeBanner;
