/**
 * Export helpers: client-side PNG of the 15x7 timetable grid via
 * html2canvas (dom-painted canvas, no SVG-foreignObject serialization).
 *
 * Pure/decidable parts are exported for vitest: the PNG filename rule
 * (timetable name + date, filesystem-safe) and the empty-grid guard.
 * Empty-grid rule: never produce a blank PNG file - the guard throws
 * EmptyGridExportError and the button surface shows the friendly copy.
 */

import html2canvas from "html2canvas";

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

/** Render the grid node to a 2x-scale PNG Blob. Uses html2canvas (a
 * DOM-walking canvas painter) instead of SVG-foreignObject serialization —
 * the latter silently returns all-white under this environment family, and
 * the white grid makes the failure indistinguishable without a detector. The
 * 25-point all-white check below converts any future recurrence into an
 * audible error instead of a silent blank PNG. */
export async function captureGridPng(
  node: HTMLElement,
  pixelRatio = 2,
): Promise<Blob> {
  const tableWrapper =
    (node.querySelector(".schedule-table-wrapper") as HTMLElement | null) ??
    (node.classList.contains("schedule-table-wrapper") ? node : null) ??
    node;

  const canvas = await html2canvas(tableWrapper, {
    scale: pixelRatio,
    backgroundColor: "#ffffff",
    useCORS: true,
    logging: false,
    onclone: (clonedDocument, element) => {
      // Sticky / scroll containers / max-height are class-driven here, so the
      // cloned document must be neutralized via ITS OWN window's computed
      // styles or the capture slips out of place (cropped thead, clipped rows).
      const view = clonedDocument.defaultView ?? window;
      element.querySelectorAll<HTMLElement>("*").forEach((el) => {
        const computed = view.getComputedStyle(el);
        if (computed.position === "sticky" || computed.position === "fixed") {
          el.style.position = "static";
        }
        if (computed.maxHeight !== "none") {
          el.style.maxHeight = "none";
        }
        if (computed.overflowX !== "visible" || computed.overflowY !== "visible") {
          el.style.overflow = "visible";
        }
      });
    },
  });

  const ctx = canvas.getContext("2d");
  if (ctx === null || canvas.width === 0 || canvas.height === 0) {
    throw new Error("PNG 匯出失敗：瀏覽器無法建立畫布，請重新整理後再試");
  }
  let contentPoints = 0;
  for (let yi = 1; yi < 6; yi += 1) {
    for (let xi = 1; xi < 6; xi += 1) {
      const px = ctx.getImageData(
        Math.floor((canvas.width * xi) / 6),
        Math.floor((canvas.height * yi) / 6),
        1,
        1,
      ).data;
      if (px[0] !== 255 || px[1] !== 255 || px[2] !== 255) {
        contentPoints += 1;
      }
    }
  }
  if (contentPoints === 0) {
    throw new Error("PNG 匯出結果為空白，請重新整理後再試；若持續發生請回報");
  }
  return await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((b) => {
      if (b === null) {
        reject(new Error("PNG 匯出失敗：無法轉換畫布內容"));
      } else {
        resolve(b);
      }
    }, "image/png");
  });
}

/** Guard + capture: the friendly-throwing entry the buttons call. */
export async function gridToPng(
  node: HTMLElement,
  courseCount: number,
): Promise<Blob> {
  assertExportable(courseCount);
  return captureGridPng(node, 2);
}

function isIOSSafari(): boolean {
  if (typeof navigator === "undefined") return false;
  const ua = navigator.userAgent;
  const isIOS = /iPhone|iPad|iPod/i.test(ua);
  const isSafari = /Safari/i.test(ua) && !/CriOS|FxiOS|EdgiOS/i.test(ua);
  return isIOS && isSafari;
}

function triggerDownload(dataUrl: string, filename: string): void {
  const anchor = document.createElement("a");
  anchor.href = dataUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
}

/** iOS Safari (iPhone/iPad) has no reliable `a.download` support for blob
 * URLs and does not render blob URLs in new tabs. On iOS the delivery path is
 * Web Share API (native share sheet) → blob-URL new tab → in-page overlay. */
async function deliverFile(
  payload: Blob,
  filename: string,
  mimeType: string,
): Promise<void> {
  if (isIOSSafari()) {
    const file = new File([payload], filename, { type: mimeType });

    if (navigator.canShare && navigator.canShare({ files: [file] })) {
      try {
        await navigator.share({ files: [file], title: filename });
        return;
      } catch (err) {
        if ((err as Error).name === "AbortError") return; // user cancelled
      }
    }

    const url = URL.createObjectURL(payload);
    const win = window.open(url, "_blank");
    if (win !== null) {
      window.setTimeout(() => URL.revokeObjectURL(url), 120_000);
    } else {
      showSaveSheet(url);
    }
    return;
  }
  const url = URL.createObjectURL(payload);
  triggerDownload(url, filename);
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

function showSaveSheet(blobUrl: string): void {
  const overlay = document.createElement("div");
  overlay.style.cssText =
    "position:fixed;inset:0;background:rgba(0,0,0,.85);z-index:9999;" +
    "display:flex;align-items:center;justify-content:center;flex-direction:column;gap:.75rem;padding:1rem";
  const img = document.createElement("img");
  img.src = blobUrl;
  img.style.cssText = "max-width:100%;max-height:80vh;border-radius:8px";
  img.alt = "timetable";
  const hint = document.createElement("div");
  hint.textContent = "長壓圖片可儲存至相簿";
  hint.style.cssText = "color:#fff;font-size:.85rem";
  const btn = document.createElement("button");
  btn.type = "button";
  btn.textContent = "關閉";
  btn.style.cssText =
    "padding:.55rem 1.6rem;border:0;border-radius:999px;font-weight:600;background:#fff;color:#111";
  btn.addEventListener("click", () => {
    overlay.remove();
    window.setTimeout(() => URL.revokeObjectURL(blobUrl), 0);
  });
  overlay.appendChild(img);
  overlay.appendChild(hint);
  overlay.appendChild(btn);
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) {
      overlay.remove();
      window.setTimeout(() => URL.revokeObjectURL(blobUrl), 0);
    }
  });
  document.body.appendChild(overlay);
}

/** PNG download of the grid. Throws EmptyGridExportError on an empty plan. */
export async function downloadGridPng(
  node: HTMLElement,
  planName: string | null | undefined,
  courseCount: number,
): Promise<string> {
  const pngBlob = await gridToPng(node, courseCount);
  const filename = buildPngFilename(planName);
  await deliverFile(pngBlob, filename, "image/png");
  return filename;
}

/** Blob download for server-streamed files (the timetable .ics). */
export async function downloadBlob(blob: Blob, filename: string): Promise<void> {
  await deliverFile(blob, filename, blob.type || "application/octet-stream");
}
