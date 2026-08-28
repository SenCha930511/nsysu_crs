# DESIGN.md — NSYSU Course Wrapper frontend (todo 10 + 11 + 12 + 16 scope)

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
| `--crs-brand` | `#009e96` | Header bar, hover accent (grid blocks, row hover rail), form focus border, `.btn-brand` fill — from upstream `WEBSITE_COLOR.mainColor` |
| `--crs-brand-dark` | `#00877f` | `.btn-brand` hover/active fill (todo 12 review fix) |
| `--crs-brand-light` | `#b2e2df` | Delete button on course blocks, header subtitle |
| `--crs-brand-glow` | `rgba(0,158,150,.25)` | Hover glow ring on course blocks; form focus ring (todo 12 review fix) |
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
  JS bundle imported yet; revisit when modals arrive in todo 16).
- **Dept datalist** is populated from depts seen in fetched pages (the API
  has no distinct-dept endpoint; typing any exact dept string works).
- **Credit filter options** likewise accumulate from fetched pages.
- **Desktop-first layout** (grid 15×7 needs width); stacked below `lg`
  breakpoints matches the upstream helper's audience.
- **window.confirm for plan deletion** (todo 11): native confirm instead of
  a Bootstrap modal; the destructive confirm-token modal in todo 16 will
  introduce the modal layer properly.

## 6. Todo 11 additions (auth/plans/selected surfaces)

- **Nav header** — `.app-nav-link` pills inside the brand bar; active route
  is a light-on-brand pill (`rgba(255,255,255,.18)`), no new tokens. Auth
  corner: student no + outline-light 登出 button, or a 登入 link when anon.
- **Login card** — centered `card` (`col-md-8 col-lg-5`) + `box-shadow-sm`;
  notices use `alert-warning` (expired) vs `alert-info` (required) so the
  two reason states are distinguishable at a glance.
- **Plan rows** — `.plan-row` mirrors the browser row language; the ACTIVE
  plan carries the same brand rail as hover (`inset 3px 0 0 var(--crs-brand)`
  on `--crs-row-hover-bg`). Primary = `StarFill text-warning` (Bootstrap
  palette), otherwise `Star text-muted`.
- **Priority rows** — `.priority-row` list-group-styled stack; drag handle
  is a bare icon button (`color: var(--bs-secondary-color)`), the drag
  preview glows with the existing `--crs-brand-glow` ring. The number input
  is a 3rem centered `form-control-sm`.
- **Selection cards** — `.selection-card` rows grouped under state badges:
  選上 `text-bg-success`, 登記加選 `text-bg-info`, 失敗 `text-bg-danger`,
  any new school state `text-bg-secondary`. Cards are quota-agnostic by
  contract (the sync payload carries no quota numbers).
- **Unknown-course marker** — plan items / selection rows whose id joins no
  catalog row show a `text-bg-secondary` 「目錄查無此課」 badge and stay
  removable; plan hydration renders them as placeholder blocks named
  「未知課程（已不在課目錄）」so the grid never silently drops a row.
- **No new CSS custom properties were added** for todo 11 surfaces;
  everything traces to `--crs-*` or Bootstrap 5 utilities.

## 7. Todo 16 additions (/write 送單中心)

- **Stage gate** — full-width `alert` on top: `alert-success` when writable
  (with 重新整理 re-probe button and a 60s auto re-probe while closed), else
  `alert-warning` with one fixed title per reason (關閉／必修確認前置／初選未
  開放／格式異動) and the school stage as a `text-bg-secondary` chip. When
  not writable the whole composer is wrapped in `<fieldset disabled>` plus a
  muted hint — affordances are DOM-disabled, not just visually dimmed.
- **Ops composer** — two `table table-sm` sections mirroring the priority-row
  vocabulary: add rows carry the reuse `.priority-input` 3rem numeric input,
  teacher/periods meta line, and the same 餘 badge palette as the browser
  (`text-bg-success` / `text-bg-danger` 額滿）; drop rows show the exact 8-char
  code as the input `placeholder`, tint `table-danger` once typed-matched,
  and an `is-invalid` + `invalid-feedback` state while typed-non-matching.
- **Preview verdicts** — per-op rows tinted purely with Bootstrap table
  variants: blocked `table-danger` + `XCircleFill`, warn `table-warning` +
  `ExclamationTriangleFill`, pass untinted + `CheckCircleFill`; the machine
  verdict is shown verbatim （衝堂 renders `衝堂（與 <code>）`). The 確認送單
  button stays `disabled` until `canConfirm`: preview writable + zero blocked
  + token minted + composer unchanged since preview.
- **Confirm modal** — the modal layer deferred in §5 arrives here, hand-rolled
  because the bootstrap JS bundle is still not imported: `.crs-modal-backdrop`
  (fixed inset overlay using the single new token `--crs-modal-backdrop:
  rgba(0,0,0,.5)` — a shade, not a palette color) + `.crs-modal` flex
  centering a `card shadow`. It lists the staged diff (+課名/志願， −課名）,
  re-asserts every drop's typed code with a 課號一致/不符 badge, and requires
  an inline password field （當次輸入 only, cleared after use, never stored).
- **Job panel** — status pill from `JOB_STATUS_COPY` tones + spinner while
  non-terminal; terminal banners: superseded `alert-warning` with the fixed
  SUPERSEDED_COPY, other terminal messages `alert-danger`. Per-op outcome
  chips use `text-bg-{tone}` from OUTCOME_COPY; school messages render
  verbatim after 學校訊息：「…」; parse_failed excerpts use native
  `<details>` (no JS dependency); 階段逾時 rows carry an inline 重新預檢
  button.
- **Reconcile widget** — bordered-top section inside the job panel, terminal
  only (hidden for session_superseded); the diff table tints matches
  `table-success` / mismatches `table-danger` with 一致/不一致 badges.
- **One new CSS custom property** (`--crs-modal-backdrop`); everything else
  traces to existing `--crs-*`, reuse of `.priority-input`, or Bootstrap 5
  table/alert/badge variants.

## 8. Todo 12 additions (export surfaces)

- **Export buttons** — plain Bootstrap `btn btn-sm btn-outline-primary` with
  the `Download` react-bootstrap-icons icon and a Chinese label
  （下載 ICS / 下載課表 PNG）; the per-plan ICS affordance in the plans
  sidebar is a `btn-outline-secondary`「ICS」chip sitting in the existing
  改名/刪除 button group. No new tokens, no custom button styling.
- **Export preview card (/plans)** — a `card mt-3` under the priority
  editor titled 「<plan>」課表預覽・匯出， body renders the exact grid being
  exported via **ScheduleTable `readOnly`** (blocks keep their deterministic
  hash colors; hover accent and delete buttons are suppressed). The preview
  and the ICS document encode the same course set (known catalog courses
  with non-empty class_time only) — what you see is what you download.
- **Export errors** — inline `alert alert-warning py-1 px-2 small` bars
  inside the card / above the home grid, carrying friendly Chinese copy
  (empty-grid guard, server 409 detail-object codes). Export failure never
  produces a file.
- **No new CSS custom properties**; PNG capture wraps the existing grid in a
  plain ref div with a white background set at capture time.

## 9. Todo 12 design-review fixes (gemma-4 critique adjudicated)

- **Mobile header wrap** (H fix) — below the `md` breakpoint the single flex
  row collapsed into character-per-line CJK stacking. The header now wraps:
  brand + auth corner on row 1 (`white-space: nowrap`), the pill nav on a
  horizontally scrollable row 2 (`overflow-x: auto`, hidden scrollbar, links
  `flex: none`). Deliberately no hamburger JS — all four destinations stay
  visible and reachable in one tap.
- **Brand form chrome** (M fix) — form controls' `:focus` state now uses
  `--crs-brand` border + `--crs-brand-glow` ring instead of Bootstrap default
  blue; the login submit is `.btn-brand` (teal fill on `--crs-brand`, darker
  `--crs-brand-dark` hover). **One new token** (`--crs-brand-dark`).
- Critique items rejected after pixel verification: "mobile quota badges
  broken" (they render as a neat 2-col set), "preview table clipped on
  mobile" (the existing `.table-responsive` already handles it), "home
  gutter loose" (`row g-3` was in place), "priority-input gap" (matches the
  row vocabulary everywhere else).
