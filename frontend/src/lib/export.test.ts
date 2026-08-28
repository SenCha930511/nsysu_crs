/**
 * Export-lib unit tests (todo 12 PNG path rules + ICS friendly errors):
 *   - empty-grid guard: 0 courses -> EmptyGridExportError, >=1 -> pass
 *   - PNG filename carries the plan name + capture date, sanitized
 *   - icsErrorMessage maps the server's 409 detail-object codes to friendly
 *     copy and keeps generic fallbacks honest
 */

import { describe, expect, it } from "vitest";

import { ApiError } from "./api";
import {
  buildPngFilename,
  EmptyGridExportError,
  assertExportable,
  icsErrorMessage,
} from "./export";

describe("assertExportable (is-empty guard)", () => {
  it("throws EmptyGridExportError at 0 (never a blank file)", () => {
    expect(() => assertExportable(0)).toThrow(EmptyGridExportError);
    expect(() => assertExportable(0)).toThrow(/課表是空的/);
  });

  it("passes at 1+ courses", () => {
    expect(() => assertExportable(1)).not.toThrow();
    expect(() => assertExportable(7)).not.toThrow();
  });
});

describe("buildPngFilename (plan name + date)", () => {
  const now = new Date(2026, 7, 28); // 2026-08-28 (month is 0-based)

  it("contains the plan name and the yyyymmdd stamp", () => {
    expect(buildPngFilename("志願A", now)).toBe("nsysu-crs-志願A-20260828.png");
  });

  it("collapses whitespace to dashes instead of spaces", () => {
    expect(buildPngFilename("我的 課表 B", now)).toBe(
      "nsysu-crs-我的-課表-B-20260828.png",
    );
  });

  it("strips filesystem-illegal characters", () => {
    expect(buildPngFilename('A/B\\C:D*E?F"G<H>I|J', now)).toBe(
      `nsysu-crs-ABCDEFGHIJ-20260828.png`,
    );
  });

  it("falls back for null/empty/unusable names", () => {
    expect(buildPngFilename(null, now)).toBe("nsysu-crs-課表-20260828.png");
    expect(buildPngFilename(undefined, now)).toBe("nsysu-crs-課表-20260828.png");
    expect(buildPngFilename("   ", now)).toBe("nsysu-crs-課表-20260828.png");
    expect(buildPngFilename("///", now)).toBe("nsysu-crs-課表-20260828.png");
  });

  it("zero-pads month/day", () => {
    expect(buildPngFilename("X", new Date(2027, 0, 5))).toContain("-20270105.png");
  });
});

describe("icsErrorMessage", () => {
  it("uses the server-phrased message from 409 detail objects when present", () => {
    const err = new ApiError(409, "plan_empty_no_events", {
      message: "此課表沒有可匯出的課程時間（尚無課程，或課程皆無上課時段資料）。",
    });
    expect(icsErrorMessage(err)).toContain("此課表沒有可匯出的課程時間");
  });

  it("maps codes directly when no server message rides along", () => {
    expect(icsErrorMessage(new ApiError(409, "plan_empty_no_events"))).toContain(
      "沒有可匯出的課程時間",
    );
    expect(icsErrorMessage(new ApiError(409, "bad_period_code"))).toContain(
      "不支援的節次代碼",
    );
  });

  it("has honest fallbacks for 404 and unexpected statuses", () => {
    expect(icsErrorMessage(new ApiError(404, "plan_not_found"))).toBe(
      "找不到這組課表（可能已被刪除）。",
    );
    expect(icsErrorMessage(new ApiError(500, "boom"))).toBe("ICS 匯出失敗（500）。");
  });
});
