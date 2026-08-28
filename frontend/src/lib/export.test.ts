/**
 * Export-lib unit tests (PNG path rules):
 *   - empty-grid guard: 0 courses -> EmptyGridExportError, >=1 -> pass
 *   - PNG filename carries the timetable name + capture date, sanitized
 */

import { describe, expect, it } from "vitest";

import {
  buildPngFilename,
  EmptyGridExportError,
  assertExportable,
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

