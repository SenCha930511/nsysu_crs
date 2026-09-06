/**
 * meExtras unit tests:
 *   - 已完成 rows -> success pill; 未完成 -> warning; anything else -> gray
 *   - grades diff chip copy carries the three counts in both languages
 */

import { describe, expect, it } from "vitest";

import { checklistStatusTone, gradesDiffText } from "./meExtras";

describe("checklistStatusTone", () => {
  it("maps 已完成 to success", () => {
    expect(checklistStatusTone("已完成")).toBe("success");
    expect(checklistStatusTone("已完成（抵免）")).toBe("success");
  });

  it("maps 未完成 to warning", () => {
    expect(checklistStatusTone("未完成")).toBe("warning");
    expect(checklistStatusTone("未完成繳費")).toBe("warning");
  });

  it("maps anything else to secondary", () => {
    expect(checklistStatusTone("辦理中")).toBe("secondary");
    expect(checklistStatusTone("")).toBe("secondary");
  });
});

describe("gradesDiffText", () => {
  it("embeds the three counts in zh copy", () => {
    expect(gradesDiffText(1, 2, 42).zh).toBe("本次同步：新增 1 / 移除 2 / 不變 42");
  });

  it("embeds the three counts in en copy", () => {
    expect(gradesDiffText(1, 2, 42).en).toBe(
      "This sync: 1 added / 2 removed / 42 unchanged",
    );
  });

  it("handles an all-zero sync", () => {
    expect(gradesDiffText(0, 0, 0).zh).toContain("新增 0");
  });
});
