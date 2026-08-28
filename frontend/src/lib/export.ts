/**
 * Export helpers (todo 12): per-plan .ics (server built) + client-side PNG
 * of the 15x7 timetable grid via html-to-image.
 *
 * Pure/decidable parts are exported for vitest: the PNG filename rule
 * (plan name + date, filesystem-safe) and the empty-grid guard / friendly
 * ICS error mapping. DOM-heavy parts (html-to-image capture, anchor
 * download) are kept thin at the module edges.
 *
 * Empty-grid rule: never produce a blank PNG file - the guard throws
 * EmptyGridExportError and the button surface shows the friendly copy
 * instead. Same honesty for ICS: the server speaks 409 detail objects
 * ({code, message}); this module maps them to UI-facing Chinese text.
 */

import { toPng } from "html-to-image";

import { ApiError } from "./api";

export const EMPTY_GRID_MESSAGE =
  "課表是空的——先去「查課·課表」加入課程，再下載 PNG。";

export class EmptyGridExportError extends Error {
  constructor() {
    super(EMPTY_GRID_MESSAGE);
    this.name = "EmptyGridExportError";
  }
}

/** Guard: throws EmptyGridExportError when there is nothing to capture. */
export function assertExportable(courseCount: number): void {
  if (courseCount <= 0) {
    throw new EmptyGridExportError();
  }
}

const ILLEGAL_FILENAME_CHARS = /[/\\:*?"<>|]/g;

/** Trim + collapse whitespace to single dashes + strip path-illegal chars. */
function sanitizePlanName(planName: string): string {
  return planName
    .replace(ILLEGAL_FILENAME_CHARS, "")
    .replace(/\s+/g, "-")
    .replace(/-{2,}/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40);
}

function pad2(n: number): string {
  return n < 10 ? `0${n}` : String(n);
}

/** ``nsysu-crs-<plan>-<yyyymmdd>.png`` - plan name + capture date in the
 * filename; falls back to 課表 when the name has no usable characters. */
export function buildPngFilename(
  planName: string | null | undefined,
  now: Date = new Date(),
): string {
  const safe = sanitizePlanName(planName ?? "");
  const base = `nsysu-crs-${safe === "" ? "課表" : safe}`;
  const stamp = `${now.getFullYear()}${pad2(now.getMonth() + 1)}${pad2(now.getDate())}`;
  return `${base}-${stamp}.png`;
}

/** Render the grid node to a 2x-scale PNG data URL (transparent-safe white
 * background so the weekend shading keeps visible contrast on any viewer). */
export async function captureGridPng(
  node: HTMLElement,
  pixelRatio = 2,
): Promise<string> {
  return toPng(node, {
    pixelRatio,
    backgroundColor: "#ffffff",
    cacheBust: false,
  });
}

/** Guard + capture: the friendly-throwing entry the buttons call. */
export async function gridToPng(
  node: HTMLElement,
  courseCount: number,
): Promise<string> {
  assertExportable(courseCount);
  return captureGridPng(node, 2);
}

function triggerDownload(dataUrl: string, filename: string): void {
  const anchor = document.createElement("a");
  anchor.href = dataUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
}

/** PNG download of the grid. Throws EmptyGridExportError on an empty plan. */
export async function downloadGridPng(
  node: HTMLElement,
  planName: string | null | undefined,
  courseCount: number,
): Promise<string> {
  const dataUrl = await gridToPng(node, courseCount);
  const filename = buildPngFilename(planName);
  triggerDownload(dataUrl, filename);
  return filename;
}

// ---------- ICS ----------

/** Friendly copy for the ICS endpoint's failure codes (409 detail objects). */
export function icsErrorMessage(err: ApiError): string {
  if (err.status === 409 && typeof err.extras.message === "string") {
    return err.extras.message; // server already phrased it for humans
  }
  if (err.status === 409 && err.detail === "plan_empty_no_events") {
    return "此課表沒有可匯出的課程時間（尚無課程，或課程皆無上課時段資料）。";
  }
  if (err.status === 409 && err.detail === "bad_period_code") {
    return "課程時間資料含有不支援的節次代碼，無法匯出 ICS。";
  }
  if (err.status === 404) {
    return "找不到這組課表（可能已被刪除）。";
  }
  return `ICS 匯出失敗（${err.status}）。`;
}

function filenameFromDisposition(disposition: string | null): string | null {
  if (disposition === null) return null;
  const star = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
  if (star !== null) {
    try {
      return decodeURIComponent(star[1] as string);
    } catch {
      // fall through to the plain filename
    }
  }
  const plain = /filename="([^"]+)"/.exec(disposition);
  return plain !== null ? (plain[1] as string) : null;
}

/** Fetch the server-built ICS for one plan and save it. Throws ApiError for
 * the caller to phrase via icsErrorMessage(). */
export async function downloadPlanIcs(planId: string): Promise<void> {
  const response = await fetch(`/api/plans/${planId}/export.ics`, {
    headers: { Accept: "text/calendar" },
  });
  if (!response.ok) {
    let detail = response.statusText;
    let extras: Record<string, unknown> = {};
    try {
      const body: unknown = await response.json();
      if (typeof body === "object" && body !== null) {
        const record = body as Record<string, unknown>;
        const d = record.detail;
        if (typeof d === "string") {
          detail = d;
          const { detail: _dropped, ...rest } = record;
          extras = rest;
        } else if (typeof d === "object" && d !== null) {
          // 409 detail objects: {code, message, ...context}
          const drec = d as Record<string, unknown>;
          const { detail: _bodyDetail, ...recordRest } = record;
          extras = { ...drec, ...recordRest };
          detail = typeof drec.code === "string" ? drec.code : detail;
        }
      }
    } catch {
      // keep statusText
    }
    throw new ApiError(response.status, detail, extras);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  try {
    const filename =
      filenameFromDisposition(response.headers.get("content-disposition")) ??
      "nsysu-crs-plan.ics";
    triggerDownload(url, filename);
  } finally {
    URL.revokeObjectURL(url);
  }
}
