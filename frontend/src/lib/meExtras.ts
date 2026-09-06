/**
 * /me page pure helpers (vitest in node env):
 *   - checklistStatusTone: regweb checklist status_text ("已完成" / "未完成")
 *     to the studio-badge tone shown next to the row
 *   - gradesDiffText: the inline "本次同步：新增 X / 移除 Y / 不變 Z" chip
 *     copy in both languages after a grades sync
 */

export type ChecklistStatusTone = "success" | "warning" | "secondary";

export function checklistStatusTone(statusText: string): ChecklistStatusTone {
  if (statusText.includes("已完成")) return "success";
  if (statusText.includes("未完成")) return "warning";
  return "secondary";
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
