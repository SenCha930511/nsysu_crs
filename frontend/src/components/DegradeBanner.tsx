/**
 * Degrade banner: polls /api/catalog/meta (stale-catalog notice) AND
 * /api/ops/state (breaker read-only posture notice) and renders a sleek,
 * centered studio pill alert. The rest of the page stays fully usable.
 * Pinned in lib/degrade.ts for vitest contracts.
 */
import { useEffect, useRef, useState } from "react";
import { ExclamationTriangleFill, InfoCircleFill } from "react-bootstrap-icons";

import { fetchCatalogMeta, fetchOpsState, type CatalogMeta } from "../lib/api";
import { bannerNotices, type BannerNotice } from "../lib/degrade";
import { useI18n } from "../lib/i18n";

const POLL_INTERVAL_MS = 60_000;

function DegradeBanner() {
  const { lang } = useI18n();
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
        bannerNotices(lastMetaRef.current, metaResult.status === "rejected", ops, lang),
      );
    };

    void poll();
    const timer = window.setInterval(() => void poll(), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      controller.abort();
      window.clearInterval(timer);
    };
  }, [lang]);

  if (notices.length === 0) {
    return null;
  }

  return (
    <div data-testid="degrade-banner" className="studio-degrade-wrapper">
      {notices.map((notice) => {
        const isBreaker = notice.kind === "breaker";
        const Icon = isBreaker ? ExclamationTriangleFill : InfoCircleFill;
        return (
          <div
            key={notice.kind}
            className={`studio-degrade-pill ${isBreaker ? "kind-breaker" : "kind-catalog"}`}
            role="alert"
            data-testid={notice.testId}
          >
            <Icon size={14} className="flex-shrink-0" />
            <span>{notice.message}</span>
          </div>
        );
      })}
    </div>
  );
}

export default DegradeBanner;
