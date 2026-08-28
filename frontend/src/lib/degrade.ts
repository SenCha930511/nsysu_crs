/**
 * Banner decision mapping (todo 17): the DegradeBanner renders zero or more
 * notices from the two pollable postures:
 *
 * - catalog meta: ingest failed (ok=false) or unreachable -> stale-catalog
 *   notice (todo 10 contract, unchanged).
 * - ops state:   breaker.state != "closed" -> read-only posture notice
 *   (school believed down; catalog/timetable stay usable, login + write are
 *   hard-off).
 *
 * Pure function so vitest pins the matrix without a DOM.
 */

import type { CatalogMeta, OpsState } from "./api";

export interface BannerNotice {
  kind: "catalog" | "breaker";
  /** Test-id suffix: degrade-banner-cat / degrade-banner-breaker */
  testId: string;
  message: string;
}

export function formatSnapshotTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso;
  }
  return date.toLocaleString("zh-TW", {
    timeZone: "Asia/Taipei",
    hour12: false,
  });
}

export function catalogNotice(
  meta: CatalogMeta | null,
  metaFetchFailed: boolean,
  lang: "zh" | "en" = "zh",
): BannerNotice | null {
  const stale = metaFetchFailed || meta === null || !meta.ok;
  if (!stale) return null;
  const updatedAt = meta?.updated_at ?? null;
  const en = lang === "en";
  return {
    kind: "catalog",
    testId: "degrade-banner-catalog",
    message:
      updatedAt !== null
        ? en
          ? `Course data was last updated at ${formatSnapshotTime(updatedAt)} (the school catalog is temporarily unreachable)`
          : `課程資料為 ${formatSnapshotTime(updatedAt)} 更新（學校目錄暫時無法同步）`
        : en
          ? "Course data update time unknown (the school catalog is temporarily unreachable)"
          : "課程資料更新時間未知（學校目錄暫時無法同步）",
  };
}

export function breakerNotice(ops: OpsState | null, lang: "zh" | "en" = "zh"): BannerNotice | null {
  if (ops === null || ops.breaker.state === "closed") return null;
  return {
    kind: "breaker",
    testId: "degrade-banner-breaker",
    message:
      lang === "en"
        ? "The school system is temporarily unavailable, so the site is in read-only safe mode: browsing and timetable work, sign-in and submissions are paused."
        : "學校系統暫時異常，本站進入唯讀安全模式：查課與課表功能維持可用，登入與送單暫停。",
  };
}

export function bannerNotices(
  meta: CatalogMeta | null,
  metaFetchFailed: boolean,
  ops: OpsState | null,
  lang: "zh" | "en" = "zh",
): BannerNotice[] {
  const notices: BannerNotice[] = [];
  const breaker = breakerNotice(ops, lang);
  if (breaker !== null) notices.push(breaker);
  const catalog = catalogNotice(meta, metaFetchFailed, lang);
  if (catalog !== null) notices.push(catalog);
  return notices;
}
