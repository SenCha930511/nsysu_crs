# Gemini UI redo — orchestrator review (2026-08-28)

User redid the frontend UI with Gemini (13 files, +1243/-623, uncommitted working
tree). Orchestrator review + repair pass, then verification and deploy check.

## Gates (post-fix)
- `npx tsc --noEmit` → clean
- vitest → **107/107** (9 files)
- `npm run build` → dist 246→247 kB css / 436 kB js, BUILD_EXIT=0
- Stack: caddy rebuilt with fixed bundle; `/api/health` 200, home 200
- Brave headless screenshots: login + home verified visually (teal theme,
  language select + reset button legible after grid fix)

## Findings → resolutions
1. 🔴 **Security regression (privacy invariant) — FIXED.** Gemini's
   ConfirmModal rewrite dropped `setPassword("")` after the submit attempt,
   leaving the password in React state — violates the plan's zero-retention
   rule （密碼僅用於當次）. Restored in the `finally` block of
   `WritePage.tsx` ConfirmModal.submit.
2. 🔴 **License compliance — FIXED.** Gemini stripped the MIT attribution
   headers from `CourseBlock.tsx` and `ScheduleTable.tsx` (adapted from
   NSYSUCourseAPI/NSYSUSelectorHelper per README Attribution). Headers
   restored (condensed, kept copyright + upstream URLs).
3. 🟡 **Dead CSS utility classes — FIXED.** Gemini used Tailwind-ish
   `px-2.5 / py-1.5 / px-3.5 / p-1.5 / mb-3.5 / gap-1.5` and
   `text-teal-600/700/800 / bg-teal-50`, none of which exist in Bootstrap
   or the new token CSS. Added compact definitions to `index.css`; the
   --crs-brand token values map 1:1 to Tailwind teal 600/700/800/50, so
   Gemini's color intent now actually renders.
4. 🟡 **Filter-row layout squish — FIXED.** `col-xl-1` language select
   unreadably narrow + reset button wrapped ("重/設"). Rebalanced row-2
   grid （系所 3→2, 語言 1→2, 統計 keep 2 → 12 cols) and made
   badge/reset `flex-shrink-0 text-nowrap`.
5. 🟡 Contract preservation — VERIFIED. Every testid, aria-label, form id,
   error-mapping branch, and data-flow prop survived; vitest 107/107 is the
   proof. New naming (LoginPage "立即登入", ScheduleTable 節→節次） cosmetic.
6. 🟡 ConfirmModal dropRows filter changed from `dropIncludable` to
   "code present in preview ops" — behaviorally equivalent for submit
   outcomes (preview ops only contain includable drops); left as-is.

## Noted, left for user to decide (no action taken)
- index.html now loads Google Fonts (Outfit / Plus Jakarta Sans) from
  googleapis.com — a third-party request on every load; trades against the
  localhost-first / 無追蹤 posture (fonts aren't trackers; offline dev
  falls back to system stack). Self-hosting (~2 woff2 files) possible.
- Token system fully replaced (`--crs-*` palette); DESIGN.md still records
  the old academic-ink lock — the redo is user-sanctioned, but DESIGN.md +
  design-review personae inputs will drift unless updated.
- Gemini stripped the intent/doc header comments from all 13 touched files;
  only the two MIT headers were restored as compliance items.
