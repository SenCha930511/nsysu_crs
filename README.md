# NSYSU Course Wrapper（中山選課外掛站）

包住中山大學選課系統（selcrs）的獨立網站：課程瀏覽與進階篩選、週課表與衝堂／學分即時檢查、名額快照、課程大綱外連、PNG 圖檔匯出、「我的已選」同步，以及經你**二次確認**才送出的真實加退選代送。
FastAPI 後端 / Vite + React 18 + TypeScript + Bootstrap 5 前端 / Postgres + Redis / Caddy 單一 HTTP 入口。

---

## 目錄（中文優先，English README follows）

1. [功能現況](#功能現況)
2. [系統架構](#系統架構)
3. [安全與身份鐵律](#安全與身份鐵律)
4. [線上部署（Quickstart）](#線上部署-quickstart)
5. [本機開發](#本機開發)
6. [測試與驗證](#測試與驗證)
7. [文件堆](#文件堆)
8. [近期履歷摘要](#近期履歷摘要)
9. [致謝與授權](#致謝與授權)

---

## 功能現況

| 層級 | 可用給 | 內容 |
|---|---|---|
| 公開 | 任何人（免登入） | 課程目錄瀏覽（虛擬滾動）、關鍵字搜尋、**進階篩選**（學系下拉 / 年級 / 學分 / 必選修 / EMI / 尚有餘額 / 星期 / 節次）、課程名稱直通學校課程大綱頁（另開分頁）、隱私／條款／FAQ、語言切換（繁中 ⇄ 英文） |
| 訪客 | 免登入 | 本地暫存選課（localStorage）、週課表預覽＋衝堂標記、學分／節數統計、PNG 課表圖匯出 |
| 登入（SSO2） | 在學學生，**慎用的實寫功能** | 學校「我的已選」同步（真義＋未對應行歸類）、暫存區加／退代辦（自動繼承志願序欄位）、Preview（送出前校對）→ 密碼二次確認 → Send（真實送單工作進 Redis 佇列，由 worker 對校內做 POST)、紀錄頁（每筆工作的詳情、逐筆成敗與真實校內回饋，如「違反限修條件」逐字帶出；學號一律脫敏為 `M123****78`)、階段／容量顯示含「最後同步時間」 |

已退役（使用者決定，git 歷史可回）：方案實驗室（多組課表／志願序／複製／對比）與 ICS 匯出。目前**沒有任何課表組合持久化層**——前端只剩主控台＋紀錄頁；Postgres 不存任何候選課表，只留真實送單的審批痕跡。

## 系統架構

```mermaid
flowchart LR
  U[瀏覽器 (訪客或 SSO2 登入)] --> C[Caddy 單入口 + 安全標頭/CSP: /static + /api 反代]
  C --> A[app FastAPI 分層路由]
  A --> P[(Postgres 6 張表)]
  A --> R[(Redis 會話/熔斷/鎖/快取/佇列)]
  A --> S[selcrs / SSO2 讀取 + 有守衛的 POST]
  W[worker: ingest cron + write queue] --> P
  W --> R
  W --> S
```

- **Caddy**（`deploy/`)：唯一對外 HTTP 入口（80/443）;`/` 走靜態 dist,`/api/*` 反代到 app；嚴格 CSP＋Permissions-Policy(html2canvas 的 img-src 只放 `data:`/`blob:`)。
- **app(FastAPI,`backend/app/`)**:
  - 讀取層：`/api/courses`（查詢＋分頁）、`/api/catalog/meta`(ingest 新鮮度）、`/api/catalog/depts`（學系下拉，Redis 快取 30 分鐘）、`/api/courses/{id}/outline`（課程大綱代理）。
  - 認證：`/api/auth/*`(SSO2 登入流、`base64md5` 變換、站內 cookie)，加上連敗鎖定與熔斷器。
  - 校內階段狀態：`GET /api/stage`（即時查詢當前校內階段）；熔斷器姿勢透過 `/api/ops/state` 顯示給 UI/CLI。
  - 寫入流水線：`POST /api/write/preview`（顯示即將送出的表單）→ `POST /api/write/submit`（密碼二次確認＋CSRF token，任務進佇列）→ `GET /api/write/jobs*`（紀錄查詢）。
  - **flat-404 慣例**：屬主資源／禁止 API 一律回 404（非 401/403)，避免外洩結構。
- **worker(`python -m app.worker`)**：定期爬入課程目錄（`offpeak='7 * * * *'` / `peak='*/10 * * * *'`）與消費寫入佇列（`writeq:jobs`)，讓真實校內 POST 不阻塞 app 進程。
- **Postgres 16(6 張表）**:`students`、`courses`（含**課別代號 `code` VARCHAR(20)**)、`ingest_runs`、`write_jobs`、`write_audit`、`write_audit_archive_meta`(hot 90 天 → gz 歸檔 → 硬刪）。
- **Redis(`maxmemory 128mb`,**noeviction**)**:SSO2 站內 session、校內憑證（`selcrs:{site_session_id}`，短 TTL)、熔斷器／鎖定狀態、depts/outline 快取、寫入佇列與 idempotency。
- **前端(`frontend/src/`)**:
  - 路由：`/`（統一主控台：查課／課表／暫存／送單；訪客與登入同構，進站優先導向 `/login`)、`/login`、`/write`（紀錄）、`/privacy`、`/tos`、`/faq`。
  - 設計系統 = Bootstrap 5 + `index.css` 自建 studio tokens(**無 Tailwind**),react-bootstrap-icons,react-virtuoso 處理大表滾動，`html2canvas` 的 PNG 引擎（含 25 點全白檢測）。
  - 能力模塊：`lib/timeslots.ts`（節次映射，源自 SelectorHelper)、`lib/selectionGrid`（含課別代號轉換）、`lib/consoleOps`（暫存 → ops)、`state/auth` × `state/selection`。
- **寫入身份（live-probed)**：校內寫入表單只認**課別代號**（短碼）；常見的 8-char 課程代碼不會解析（證據：`qa/probe-crsno-desc.txt`)。

## 安全與身份鐵律

1. **不碰你帳號內現有的課**——探頭一律使用不存在的 `ZZ999999` 錯碼；絕不做真實加選探頭。
2. **資料庫零憑證**：密碼不落地；校內憑證只在 Redis 且短 TTL;`write_audit` 只用 salted `stuid_hash` 關聯。
3. **寫入用短碼；任何破壞性行為在主控台由你手動二次確認才送出**——送出後的行為以你的身分代表（服務條款中明示責任歸屬）。
4. **一切安裝皆 venv / 容器 / 局部 node_modules**；萬一需要全域安裝必須記入 `qa/install-log.md` 並事後移除。
5. **git**：原子 commits、不 orphan、每個邏輯提交立即 `git push origin main`；私有 repo 的歷史有已知密碼污點 `39beccb`（已說明）。
6. **CSP 嚴格**:`script-src 'self'`，沒有 inline JS——除錯臨時頁只能是靜態檔。

## 線上部署 (Quickstart)

```bash
cp .env.example .env   # 填入 APP_SECRET 等（非本機必要項）
docker compose -f deploy/docker-compose.yml up --build -d
curl -sf http://localhost/api/health        # via Caddy（唯一對外入口）
curl -sf http://localhost/                  # 前端頁
curl -sf http://localhost/api/ops/state     # 熔斷器姿勢
```

- 只有 caddy 對外接埠；host 端除錯請用 `docs/runbook.md` §1 的 untracked override（勿推上倉庫）;
- **備份**：`scripts/backup.sh`(pg_dump | gzip → `deploy/backups/`，保留最近 14 份）;restore SOP 與 cron 在 runbook 裡；
- **熱補的教訓**：「部分檔案熱補」可能與容器內的舊 pycache 不一致——改過 router/model 類模組後，建議直接 `docker compose up --build -d`（或至少重啟受影響服務）；這類踩坑有現場實錄。

## 本機開發

```bash
# Dev（熱重載）
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml up --build
# 或不走 Docker（選配）
cd backend && uv python install 3.12 && uv sync && uv run uvicorn app.main:create_app --factory --reload
cd frontend && npm install && npm run dev   # 會把 /api 代理到 localhost:8000
```

- **資料庫遷移**:`docker compose -f deploy/docker-compose.yml exec app alembic upgrade head`;
- 前後端都是 types-first；生產碼禁用 `as any`。

## 測試與驗證

```bash
cd backend && uv run pytest          # Hermetic；依賴 compose Postgres 的測試在連不到時自動 skip（88 個）
cd frontend && npx vitest run        # 104 個測試，tsc 生產淨
```

- compose-coupled 測試請手動：`docker compose -f deploy/docker-compose.yml cp backend/tests app:/app/tests`，再 `docker compose -f deploy/docker-compose.yml exec -T app sh -lc 'cd /app && uv run --no-sync --with pytest python -m pytest tests/... -q'`;
- 端到端證據（登入/暫存/送單/紀錄）：見 `qa/` 的每波 log + 瀏覽器圖；
- 測試策略（§3）：**密碼不寫磁碟、真加選探頭只用錯碼、測試絕不碰你帳號現有課程**。

## 文件堆

- `docs/architecture.md`：活的架構契約（secrets 政策、write pipeline、queue、PII 生命周期）;
- `docs/runbook.md`：運營兵符（backup restore、容器 override、環境變數表）;
- `docs/launch-checklist.md`:115-2 上架前的 F1–F4 狀態機（審查約束）;
- `docs/verified-facts.md`：與校內**即時互動過**的事實清單（探頭筆記＋失敗回饋解析）;
- `qa/*.log/.png`:17 波驗證＋後續補證的原始檔；
- `.omo/plans/nsysu-course-wrapper.md`:17-todo 初始 work plan（歷史文件）。

## 近期履歷摘要

- 全站雙語（自製零依賴 i18n，切換鈕置於導航）;
- 紀錄頁帶出**逐筆失敗原因**與學號脫敏；
- 全新紀錄頁；少了舊的 `/selected` 頁；學系下拉從校內來源直出；
- PNG 引擎換到 `html2canvas`（html-to-image 在 CSP 下只出白圖）；自製 FLUX 品牌 logo;
- **移除方案實驗室**（使用者決定）：多組課表、複製、對比、ICS 全部拔除；任何課表組合都不會再持久化（災情見 `0003_drop_plans`)。

## 致謝與授權

改編自以下 MIT 授權專案（每個改造的檔案都帶 copyright header):

- [NSYSU-OpenDev/NSYSUCourseAPI](https://github.com/NSYSU-OpenDev/NSYSUCourseAPI) — 課程目錄欄位解析
- [NSYSU-OpenDev/NSYSUSelectorHelper](https://github.com/NSYSU-OpenDev/NSYSUSelectorHelper) — 週課表格版／節次／衝堂邏輯
- [edwinchu0711/NsysuApp_OpenSource](https://github.com/edwinchu0711/NsysuApp_OpenSource) — SSO2 `base64md5` 登入變換與選課服務行為
- [nsysu-code-club/NSYSU-AP](https://github.com/nsysu-code-club/NSYSU-AP) — SSO2 登入流程參考
- [Hua777/NSYSUSelcrs](https://github.com/Hua777/NSYSUSelcrs) — **唯讀參考**,其 repo 無 LICENSE，未複製任何 code

---

---

# NSYSU Course Wrapper (English)

A standalone wrapper site around NSYSU's course-selection system (selcrs): catalog browsing and advanced filters, weekly timetable with realtime clash/credit checks, availability snapshots, syllabus links, PNG export, "my selections" sync, and — only after your explicit **second confirmation** — real add/drop submissions on your behalf.
FastAPI backend / Vite + React 18 + TypeScript + Bootstrap 5 frontend / Postgres + Redis / Caddy as the single HTTP entry.

---

## Contents

1. [Features](#features)
2. [Architecture](#architecture)
3. [Safety & identity invariants](#safety--identity-invariants)
4. [Production deploy (Quickstart)](#production-deploy-quickstart)
5. [Local development](#local-development)
6. [Testing & verification](#testing--verification)
7. [Docs](#docs)
8. [Recent history (summary)](#recent-history-summary)
9. [Attribution & licenses](#attribution--licenses)

---

## Features

| Tier | Availability | Notes |
|---|---|---|
| Public | anonymous | Course catalog browsing (virtualized scrolling), keyword search, **advanced filters** (department dropdown / grade / credit / compulsory-elective / EMI / seats-left / weekday / period), course names link directly to the school's syllabus page (new tab), Privacy/Terms/FAQ, language toggle (繁中 ⇄ English) |
| Guest | anonymous | Locally staged selections (localStorage), weekly timetable with clash markers, credits/hours totals, PNG export of the grid |
| Signed-in (SSO2) | **real write power, use deliberately** | School "my selections" sync (real truth + unresolved rows clearly separated); staging add/drop intents with inherited priority fields; Preview (form echo) → password re-confirmation → Send (real write job enqueued to Redis and executed by the worker against the school POST); Records page (the full job ledger, per-op outcome with the school-reported reason verbatim — e.g. "違反限修條件" — and student numbers masked as `M123****78`); stage and availability displays with last-sync timestamps |

Retired (user decision, fully recoverable from git): the Plan Lab (multi-plan deck/priorities/clone/compare) and ICS export. There is currently **no planner persistence at all** — the frontend has only the console + records; Postgres holds nothing other than the auditable artifacts of real write jobs.

## Architecture

```mermaid
flowchart LR
  U[browser (guest or SSO2-signed)] --> C[Caddy single entry + security headers/CSP: static + /api reverse-proxy]
  C --> A[app FastAPI route tiers]
  A --> P[(Postgres 6 tables)]
  A --> R[(Redis session/breaker/lock/caches/queues)]
  A --> S[selcrs/SSO2 reads + gated POSTs]
  W[worker ingest crons + write queue] --> P
  W --> R
  W --> S
```

- **Caddy** (`deploy/`): the only outward HTTP entry (80/443); `/` serves the built dist, `/api/*` reverse-proxies to app; strict CSP + Permissions-Policy (html2canvas is limited to `data:`/`blob:` img-src).
- **app** (`backend/app/`):
  - read tier — `/api/courses` (query + pagination), `/api/catalog/meta` (ingest freshness), `/api/catalog/depts` (department dropdown, Redis-cached 30 min), `/api/courses/{id}/outline` (syllabus proxy);
  - auth — `/api/auth/*` (SSO2 login flow, `base64md5` transform, site cookie), plus lockout + circuit breaker;
  - live stage state — `GET /api/stage` (current school phase, realtime); breaker posture exposed via `/api/ops/state`;
  - write pipeline — `POST /api/write/preview` (echo of the exact form to be sent) → `POST /api/write/submit` (password re-confirmation + CSRF token, job queued) → `GET /api/write/jobs*` (records);
  - **flat-404 convention**: owner-scoped/API-forbidden resources answer 404 (not 401/403) to avoid leaking structure.
- **worker** (`python -m app.worker`): periodic catalog ingest (`offpeak='7 * * * *'` / `peak='*/10 * * * *'`) plus the write-job queue (`writeq:jobs`), so real school POSTs never block the app.
- **Postgres 16 (6 tables)**: `students`, `courses` (with **`code` VARCHAR(20)**, the 課別代號), `ingest_runs`, `write_jobs`, `write_audit`, `write_audit_archive_meta` (hot 90 days → gz archive → delete).
- **Redis** (`maxmemory 128mb` + **noeviction**): site sessions, school credentials (`selcrs:{site_session_id}` with short TTL), breaker/lockout state, dept/outline caches, write queue / idempotency.
- **frontend** (`frontend/src/`):
  - routes — `/` (unified console: browse/timetable/staging/send, same layout for guests and signed-in users, login-priority redirect before any route), `/login`, `/write` (records), `/privacy`, `/tos`, `/faq`;
  - design system = Bootstrap 5 + `index.css` studio tokens (**no Tailwind**), react-bootstrap-icons, react-virtuoso for large lists, `html2canvas` for PNG (with a 25-point all-white detector);
  - discrete capabilities — `lib/timeslots.ts` (period mapping, adapted from SelectorHelper), `lib/selectionGrid` (incl. identity-code conversion), `lib/consoleOps` (staging → ops), `state/auth` × `state/selection`.
- **write identity (live-probed)**: the school write form only understands the **課別代號 (short code)**; the 8-char 课程代碼 does NOT resolve (probe evidence: `qa/probe-crsno-desc.txt`).

## Safety & identity invariants

1. **Never touch the account's existing courses** — probes use only the nonexistent code `ZZ999999`; no real add probes at all.
2. **Zero credentials in the database**: passwords never land in Postgres; school credentials live only in Redis with a short TTL; `write_audit` correlates by salted `stuid_hash`.
3. **Write uses short codes; a human-in-the-loop second confirmation** in the console precedes any real send (the Terms spell the responsibility boundary).
4. **All installs live in venv / containers / local node_modules only**; any exception must be recorded in `qa/install-log.md` and removed afterwards.
5. **git**: atomic commits, never orphan branches, `git push origin main` immediately after each logical commit; private repo for now with a known historical credential stain at `39beccb` (documented).
6. **CSP is strict**: no inline JS (`script-src 'self'`) — debugging harnesses must be static files, not `<script>` injection.

## Production deploy (Quickstart)

```bash
cp .env.example .env   # fill APP_SECRET etc. for anything non-local
docker compose -f deploy/docker-compose.yml up --build -d
curl -sf http://localhost/api/health        # via Caddy (the only published entry)
curl -sf http://localhost/                  # frontend page
curl -sf http://localhost/api/ops/state     # breaker posture
```

- Only caddy publishes ports; for host debugging use the untracked override in `docs/runbook.md` §1;
- **Backups**: `scripts/backup.sh` (pg_dump | gzip → `deploy/backups/`, keeps newest 14); restore SOP + cron in the runbook;
- **Hot-patch lesson**: a partial file-level patch can disagree with stale pycache inside containers — after touching router/model modules, prefer a full `docker compose up --build -d` (or at least restart the affected service); there's live evidence of this species of failure.

## Local development

```bash
# Dev (hot reload)
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml up --build
# Or bare-machine (optional)
cd backend && uv python install 3.12 && uv sync && uv run uvicorn app.main:create_app --factory --reload
cd frontend && npm install && npm run dev   # proxies /api to localhost:8000
```

- **Migrations**: `docker compose -f deploy/docker-compose.yml exec app alembic upgrade head`;
- Everything is types-first; `as any` is forbidden in production code.

## Testing & verification

```bash
cd backend && uv run pytest          # hermetic; PostgreSQL-coupled tests auto-skip when DB unavailable (88 skips)
cd frontend && npx vitest run        # 104 tests, tsc clean as a gate
```

- Compose-coupled tests by hand: `docker compose -f deploy/docker-compose.yml cp backend/tests app:/app/tests` then `docker compose -f deploy/docker-compose.yml exec -T app sh -lc 'cd /app && uv run --no-sync --with pytest python -m pytest tests/... -q'`;
- End-to-end evidencetery (login/staging/send/records): per-wave logs + browser screenshots under `qa/`;
- Test policy (§3): **no passwords are written to disk, live-add probes use only the wrong code `ZZ999999`, and no test ever touches the user's real courses**.

## Docs

- `docs/architecture.md`: the living contract (secrets policy, write pipeline layers, queue layout, PII lifecycle);
- `docs/runbook.md`: operations commandments (backup restore, container service overrides, env-var table);
- `docs/launch-checklist.md`: 115-2 pre-launch F1–F4 state machine (review-gated);
- `docs/verified-facts.md`: interactive facts **live-verified against the school** (probe notes + failure-reason parsing rules);
- `qa/*.log/.png`: 17 waves of verification evidence + later proofs;
- `.omo/plans/nsysu-course-wrapper.md`: the original 17-todo work plan (historical).

## Recent history (summary)

- Full bilingual UI (custom zero-dep i18n with an nav-mounted language toggle)
- Per-op failure reasons on the records page, student-number masking
- Records page + retirement of the old /selected grid; department dropdown fed by the school signal itself
- PNG engine swapped to html2canvas (the old html-to-image rendered all-white under the CSP); custom FLUX-generated logo
- **Plan Lab removed** (user decision): multi-plan deck, clone, compare, ICS — nothing planner-shaped persists anywhere now (audit of the removal lives in `0003_drop_plans`)

## Attribution & licenses

Adapted from the following MIT-licensed projects (each adapted file carries a copyright header):

- [NSYSU-OpenDev/NSYSUCourseAPI](https://github.com/NSYSU-OpenDev/NSYSUCourseAPI) — course catalog field parsing
- [NSYSU-OpenDev/NSYSUSelectorHelper](https://github.com/NSYSU-OpenDev/NSYSUSelectorHelper) — weekly timetable grid / timeslot & conflict logic
- [edwinchu0711/NsysuApp_OpenSource](https://github.com/edwinchu0711/NsysuApp_OpenSource) — SSO2 `base64md5` login transform and selection-service behavior
- [nsysu-code-club/NSYSU-AP](https://github.com/nsysu-code-club/NSYSU-AP) — SSO2 login flow reference
- [Hua777/NSYSUSelcrs](https://github.com/Hua777/NSYSUSelcrs) — **read-only archaeological reference only**; its repo has no LICENSE and no code was copied from it
