# DESIGN.md — NSYSU Course Wrapper frontend (todo 10 scope)

Read-only core UI: course browser + weekly timetable. This document is the
token contract for the components under `src/`; later todos (11/12/16) extend
it rather than restyle.

## 0. Source of truth / adaptation note

The timetable grid, course block, conflict rule, and badge vocabulary are a
faithful adaptation of
[NSYSU-OpenDev/NSYSUSelectorHelper](https://github.com/NSYSU-OpenDev/NSYSUSelectorHelper)
(MIT) — header comments in `src/config/timeslots.ts`, `src/lib/conflicts.ts`,
`src/lib/totals.ts`, `src/components/ScheduleTable.tsx`, and
`src/components/CourseBlock.tsx` carry the attribution. Styling uses
**Bootstrap 5 utility classes as the design-token system**; only values
Bootstrap does not provide are CSS custom properties in `src/index.css`
(`--crs-*`). Do not introduce one-off hex codes outside `:root`.

## 1. Tokens

| Token | Value | Use |
|---|---|---|
| `--crs-brand` | `#009e96` | Header bar, hover accent (grid blocks, row hover rail) — from upstream `WEBSITE_COLOR.mainColor` |
| `--crs-brand-light` | `#b2e2df` | Delete button on course blocks, header subtitle |
| `--crs-brand-glow` | `rgba(0,158,150,.25)` | Hover glow ring on course blocks |
| `--crs-weekend-bg` | `#e9ebef` | Weekend grid columns |
| `--crs-conflict-bg` | `var(--bs-warning-bg-subtle)` | Conflict-tinted list rows |
| `--crs-row-hover-bg` | `#f3f8f8` | Hovered list row background |

Bootstrap tokens for everything else: spacing (`g-2`, `mb-1`, `py-*`),
`text-bg-*` badge palette, `table-secondary`, `form-select-sm`, etc.

## 2. Component anatomy

- **ScheduleTable** — 15 period rows × 7 weekday columns HTML table
  (`table-layout: fixed`, timeslot column 3.4rem, font-size .75rem). Weekend
  columns shaded. Left column shows period code + clock range
  (`07:00–07:50` style).
- **CourseBlock** — name (bold) + room lines, deterministic light hash color
  (brightness-masked), hover → brand color + white text + glow, floating
  delete button (Trash3, visible on hover). Multiple blocks per cell stack.
- **CourseBrowser row** — main: name_zh + name_en, meta line
  (dept · grade · class · teacher), compact time tags (`三56`). Side:
  compulsory / credit / EMI badges, quota block, add/remove button.
- **Quota badges** — 限 `text-bg-secondary` (restrict), 登 `text-bg-info`
  (select_n), 上 `text-bg-primary` (selected_n), 餘 `text-bg-success`
  (remaining > 0) / `text-bg-danger` + "額滿" (remaining ≤ 0). Null → "–".
- **Credit badge** — 0 → secondary, 1 → info, 2 → primary, 3 → success,
  ≥4 → warning; null → light.
- **Compulsory** — 必修 `text-bg-danger`; 選修 `text-bg-light border`.
- **EMI** — `text-bg-dark`.
- **Conflict row tint** — `--crs-conflict-bg` + native `title` tooltip naming
  the clashing course(s) and overlapping slots (`與已選「線性代數」（三5）衝堂`).
- **TotalsPanel** — 已選 N 門 (light) / 總學分 (primary) / 總時數 (info) /
  衝堂 N 組 (danger, tooltip lists pairs).
- **DegradeBanner** — full-width `alert alert-warning` above the header when
  `/api/catalog/meta` is `ok=false` or unreachable.

## 3. Motion & interaction rules

- Only `background-color` / `box-shadow` transitions (120ms) on rows and
  blocks. No layout-affecting animation; no decorative motion.
- Hover sync list ↔ grid is keyed by course id through `App` state; both
  sides render the same accent (brand rail on rows, brand fill on blocks).

## 4. Accessibility

- Native `title` tooltips (conflict detail, quota meanings) — no JS tooltip
  dependency. Conflict rows additionally carry a semantic class, not just a
  color (`.course-row-conflict`).
- All interactive elements are real `<button>`s with aria-labels where the
  label is icon-only (block delete); filter selects have `aria-label`.
- "共 N 門" counter is `aria-live="polite"`.

## 5. Accepted debt

- **Native title tooltips** instead of Bootstrap JS tooltips (no bootstrap
  JS bundle imported yet; revisit when modals arrive in todo 11/16).
- **Dept datalist** is populated from depts seen in fetched pages (the API
  has no distinct-dept endpoint; typing any exact dept string works).
- **Credit filter options** likewise accumulate from fetched pages.
- Desktop-first layout (grid 15×7 needs width); stacked below `lg`
  breakpoints matches the upstream helper's audience.
