/**
 * /me page pure helpers (vitest in node env):
 *   - checklistStatusTone: regweb checklist status_text to studio-badge tone
 *   - formatChecklistStatus: maps raw status to tone and localized label (never empty)
 *   - splitBilingualText: separates Chinese primary text and English secondary text
 *   - sanitizeChecklistPeriod: deduplicates redundant titles and formats dates cleanly
 *   - gradesDiffText: the inline "本次同步：新增 X / 移除 Y / 不變 Z" chip copy
 */

export type ChecklistStatusTone = "success" | "warning" | "secondary";

export interface FormattedChecklistStatus {
  tone: ChecklistStatusTone;
  label: string;
}

export function checklistStatusTone(statusText: string): ChecklistStatusTone {
  const lower = statusText.toLowerCase();
  if (
    statusText.includes("已完成") ||
    statusText.includes("已繳費") ||
    statusText.includes("已確認") ||
    statusText.includes("已閱讀") ||
    lower.includes("completed") ||
    lower.includes("complete") ||
    lower.includes("done")
  ) {
    return "success";
  }
  if (
    statusText.includes("未完成") ||
    statusText.includes("待辦") ||
    statusText.includes("審核中")
  ) {
    return "warning";
  }
  return "secondary";
}

export function formatChecklistStatus(
  statusText: string,
  lang: "zh" | "en",
): FormattedChecklistStatus {
  const tone = checklistStatusTone(statusText);
  const lower = statusText.toLowerCase();

  if (tone === "success") {
    if (statusText.includes("已繳費")) {
      return { tone: "success", label: lang === "zh" ? "已繳費" : "Paid" };
    }
    return { tone: "success", label: lang === "zh" ? "已完成" : "Completed" };
  }

  if (
    statusText.includes("免辦") ||
    statusText.includes("不影響") ||
    lower.includes("n/a")
  ) {
    return { tone: "secondary", label: lang === "zh" ? "免辦" : "Optional" };
  }

  if (statusText.includes("審核中")) {
    return { tone: "warning", label: lang === "zh" ? "審核中" : "In Review" };
  }

  if (statusText.includes("未完成")) {
    return { tone: "warning", label: lang === "zh" ? "未完成" : "Incomplete" };
  }

  // Default fallback when statusText is empty or informational instructions
  return { tone: "secondary", label: lang === "zh" ? "待辦理" : "Pending" };
}

export function splitBilingualText(raw: string): { zh: string; en: string } {
  const trimmed = raw.trim();
  const match = trimmed.match(
    /^([\u4e00-\u9fa5\u3000-\u303f\uff00-\uffef0-9\/\(\)\s\-、~～]+?)\s+(\(?[A-Za-z].*)$/,
  );
  if (match && match[1] && match[2]) {
    return { zh: match[1].trim(), en: match[2].trim() };
  }
  return { zh: trimmed, en: "" };
}

export function sanitizeChecklistPeriod(
  title: string,
  period: string,
  lang: "zh" | "en",
): string {
  const p = period.trim();
  const t = title.trim();
  if (!p) return "";
  // If period is identical or redundant with title, discard the duplicate line
  if (p === t || t.includes(p) || p.includes(t)) return "";

  const split = splitBilingualText(p);
  if (lang === "en" && split.en) return split.en;
  if (split.zh) return split.zh;
  return p;
}

export function gradesDiffText(
  added: number,
  removed: number,
  unchanged: number,
): { zh: string; en: string } {
  return {
    zh: `本次同步：新增 ${added} / 移除 ${removed} / 不變 ${unchanged}`,
    en: `This sync: ${added} added / ${removed} removed / ${unchanged} unchanged`,
  };
}
