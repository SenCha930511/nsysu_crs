/**
 * meExtras unit tests:
 *   - 已完成 rows -> success pill; 未完成 -> warning; anything else -> gray
 *   - grades diff chip copy carries the three counts in both languages
 */

import { describe, expect, it } from "vitest";

import {
  checklistStatusTone,
  formatChecklistStatus,
  gradesDiffText,
  sanitizeChecklistPeriod,
  splitBilingualText,
} from "./meExtras";

describe("checklistStatusTone", () => {
  it("maps 已完成 to success", () => {
    expect(checklistStatusTone("已完成")).toBe("success");
    expect(checklistStatusTone("已完成（抵免）")).toBe("success");
    expect(checklistStatusTone("已繳費 Completed")).toBe("success");
    expect(checklistStatusTone("已確認資料，請於期限內繳交申請表。 Done")).toBe("success");
    expect(checklistStatusTone("已閱讀 complete")).toBe("success");
  });

  it("maps 未完成 to warning", () => {
    expect(checklistStatusTone("未完成")).toBe("warning");
    expect(checklistStatusTone("未完成繳費")).toBe("warning");
    expect(checklistStatusTone("審核中")).toBe("warning");
  });

  it("maps anything else to secondary", () => {
    expect(checklistStatusTone("辦理中")).toBe("secondary");
    expect(checklistStatusTone("")).toBe("secondary");
    expect(checklistStatusTone("免辦")).toBe("secondary");
  });
});

describe("formatChecklistStatus", () => {
  it("formats completed and paid statuses", () => {
    expect(formatChecklistStatus("已完成!", "zh")).toEqual({
      tone: "success",
      label: "已完成",
    });
    expect(formatChecklistStatus("已繳費 Completed", "zh")).toEqual({
      tone: "success",
      label: "已繳費",
    });
    expect(formatChecklistStatus("已繳費 Completed", "en")).toEqual({
      tone: "success",
      label: "Paid",
    });
  });

  it("formats optional/waived statuses", () => {
    expect(formatChecklistStatus("免辦", "zh")).toEqual({
      tone: "secondary",
      label: "免辦",
    });
    expect(formatChecklistStatus("本項目不影響任何註冊程序", "en")).toEqual({
      tone: "secondary",
      label: "Optional",
    });
  });

  it("never returns empty string for empty input", () => {
    expect(formatChecklistStatus("", "zh")).toEqual({
      tone: "secondary",
      label: "待辦理",
    });
    expect(formatChecklistStatus("", "en")).toEqual({
      tone: "secondary",
      label: "Pending",
    });
  });
});

describe("splitBilingualText", () => {
  it("splits Chinese and English cleanly", () => {
    const s1 = splitBilingualText("確認個人基本資料 Personal information confirmation");
    expect(s1.zh).toBe("確認個人基本資料");
    expect(s1.en).toBe("Personal information confirmation");

    const s2 = splitBilingualText("學生自傳 Autobiography");
    expect(s2.zh).toBe("學生自傳");
    expect(s2.en).toBe("Autobiography");
  });

  it("handles Chinese-only text without error", () => {
    const s = splitBilingualText("學生銀行/郵局帳號資料");
    expect(s.zh).toBe("學生銀行/郵局帳號資料");
    expect(s.en).toBe("");
  });
});

describe("sanitizeChecklistPeriod", () => {
  it("discards duplicate period that matches title", () => {
    const res = sanitizeChecklistPeriod(
      "確認個人基本資料 Personal information confirmation",
      "確認個人基本資料 Personal information confirmation",
      "zh",
    );
    expect(res).toBe("");
  });

  it("extracts clean Chinese date in zh mode", () => {
    const res = sanitizeChecklistPeriod(
      "學生自傳 Autobiography",
      "8月3日-9月7日 August.3 rd - September.7 th",
      "zh",
    );
    expect(res).toBe("8月3日-9月7日");
  });

  it("extracts clean English date in en mode", () => {
    const res = sanitizeChecklistPeriod(
      "學生自傳 Autobiography",
      "8月3日-9月7日 August.3 rd - September.7 th",
      "en",
    );
    expect(res).toBe("August.3 rd - September.7 th");
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
