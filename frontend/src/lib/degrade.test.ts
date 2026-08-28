import { describe, expect, it } from "vitest";

import type { CatalogMeta, OpsState } from "./api";
import { bannerNotices, breakerNotice, catalogNotice } from "./degrade";

const healthyMeta: CatalogMeta = {
  ok: true,
  updated_at: "2026-08-28T00:52:22.378510Z",
  row_count: 1234,
  source: "self-scrape",
};

const failedMeta: CatalogMeta = {
  ok: false,
  updated_at: "2026-08-27T12:00:00.000000Z",
  row_count: 1200,
  source: "self-scrape",
};

function opsWith(state: string): OpsState {
  return {
    breaker: {
      state,
      mode: state === "closed" ? "normal" : "read-only",
      streak: null,
      opened_at: null,
      failure_threshold: null,
      recovery_after: null,
      probe_gate_seconds: null,
    },
    lockouts: null,
  };
}

describe("catalogNotice", () => {
  it("is null when the newest ingest round succeeded", () => {
    expect(catalogNotice(healthyMeta, false)).toBeNull();
  });

  it("renders the last-snapshot timestamp when ok=false", () => {
    const notice = catalogNotice(failedMeta, false);
    expect(notice).not.toBeNull();
    expect(notice!.kind).toBe("catalog");
    expect(notice!.testId).toBe("degrade-banner-catalog");
    expect(notice!.message).toContain("學校目錄暫時無法同步");
    expect(notice!.message).toContain("2026"); // formatted snapshot time present
  });

  it("keeps the last-known snapshot time through a transient poll failure", () => {
    const notice = catalogNotice(healthyMeta, true);
    expect(notice!.message).toContain("學校目錄暫時無法同步");
    expect(notice!.message).toContain("2026");
  });

  it("falls back to the unknown-time message when no meta exists at all", () => {
    expect(catalogNotice(null, false)!.message).toBe(
      "課程資料更新時間未知（學校目錄暫時無法同步）",
    );
    expect(catalogNotice(null, true)!.message).toBe(
      "課程資料更新時間未知（學校目錄暫時無法同步）",
    );
  });
});

describe("breakerNotice", () => {
  it("is null when the breaker is closed or state unavailable (fail-quiet)", () => {
    expect(breakerNotice(opsWith("closed"))).toBeNull();
    expect(breakerNotice(null)).toBeNull();
  });

  it("describes the read-only posture while open or half-open", () => {
    for (const state of ["open", "half-open"]) {
      const notice = breakerNotice(opsWith(state));
      expect(notice).not.toBeNull();
      expect(notice!.testId).toBe("degrade-banner-breaker");
      expect(notice!.message).toContain("唯讀安全模式");
      expect(notice!.message).toContain("登入與送單暫停");
    }
  });
});

describe("bannerNotices", () => {
  it("stacks the breaker notice above the catalog notice", () => {
    expect(bannerNotices(failedMeta, false, opsWith("open")).map((n) => n.kind)).toEqual([
      "breaker",
      "catalog",
    ]);
    expect(bannerNotices(failedMeta, false, opsWith("closed")).map((n) => n.kind)).toEqual([
      "catalog",
    ]);
    expect(bannerNotices(healthyMeta, false, opsWith("open")).map((n) => n.kind)).toEqual([
      "breaker",
    ]);
    expect(bannerNotices(healthyMeta, false, opsWith("closed"))).toEqual([]);
  });
});
