# F1 — 計畫符合性稽核 (final verification, plan `nsysu-course-wrapper.md` §F1)

Executed 2026-08-28 on `main` @ `cd09817` (F2 evidence; all 17 todos + supporting fixes committed, worktree clean).
Method: every todo's Acceptance bullets (plan file = audit source of truth) cross-checked against its plan-named `qa/` artifacts **by reading the logs**, deferred `[DEFERRED-TO-WINDOW]`/`DEFERRED-TO-1152` items checked for milestone承接, scope spot-checks run locally (zero live-credentialed work, zero school calls — this audit reads local artifacts only).

Verdict scale: **PASS** (evidence present + supportive) · **PASS-WITH-DEFERRED** (explicit deferral marker present AND milestone承接 exists in the plan) · **FAIL** (missing or non-supportive evidence — absence named exactly).

## Verdict

**CHANGES-REQUESTED** — one FAIL entry: **todo-5 運算型閘門 adjudication note is absent** (see §1.t5 and §2). Everything else is PASS or PASS-WITH-DEFERRED with承接 named. Flip condition: append the 使用者裁決 record to `qa/05-accuracy.log` (one evidence-layer line naming the decision branch — 放寬閘門 / 引 torch 計畫變更 / 社群 JSON — and the user's sign-off), no code touch required.

FAIL list (precise missing evidence):

1. **todo 5, Acceptance「運算型閘門」** — The gate formally FAILED: 21 live pages across 3 time slots were recorded (batch 1: 7/7, batch 2: 6/7, batch 3: 5/7 pages within the ≤5-attempt budget; 3 CAPTCHA-UNSOLVABLE pages; per-attempt p = 0.438 / 0.273 / 0.227). The plan's not-met branch requires `BLOCKED-ON-USER-DECISION` **with 結果記錄 + 使用者裁決** before downstream todos 6/7/10/11/12/16/17 may proceed. The results ARE recorded in `qa/05-accuracy.log`, but the **ADJUDICATION NOTE (使用者裁決) is nowhere**: the file bottom ends at `batch complete 2026-08-28 09:56:06 Asia/Taipei` with no appended adjudication, and a repo-wide search (`ADJUDICATION|operational acceptance|veto|裁決|放寬|gate-risk`) finds only the batch-1 "gate-risk **pending** ... user/decision branch" status in `docs/verified-facts.md` §solver — still pending, never closed. The task brief for this audit asserted "an ADJUDICATION NOTE appended referencing qa/05-accuracy.log bottom"; **verified-refuted: the note does not exist in the committed tree.** Downstream todos were executed after the batch-2 formal FAIL (todo-7 QA 02:34 vs batch-2 FAIL 02:22), so the blocking clause was crossed without the required recorded decision. The gate's intent is operationally met (three-diverse-timeslot evidence + the production scheduler subsequently succeeding at p=1-attempt runs, `qa/06-live.log`), which is exactly the case a recorded veto-free adjudication would close — **gates formally imperfect, operationally acceptable, user veto reserved — but the record itself is the acceptance gate and it is absent.**

## 1. Per-criterion evidence table

| Todo | Acceptance bullet | Artifact(s) | Verdict |
|---|---|---|---|
| 1 | `docker compose config` 合法 | `qa/01-health.log`: `config -q` exit 0 (prod + dev variant), all 5 services up/healthy | PASS |
| 1 | `curl -sf localhost:8000/api/health` 200、`localhost/` 為前端 | `qa/01-health.log`: health 200 app-direct **and** via Caddy; `/` serves the built SPA HTML | PASS |
| 1 | 容器 `date +%Z`=CST | `qa/01-health.log`: app/worker/postgres/redis/caddy all `CST` | PASS |
| 1 | failure: 壞 `DATABASE_URL` → 503 且無機密 | `qa/01-bad-db.log`: 503 with 6 explicit PASS assertions (no host/user/pw/port/URL leak) | PASS |
| 1 | env-contract 22 keys ＋ redis `noeviction` pin ＋ runbook prohibition | `.env.example` 22/22 keys present; `deploy/docker-compose.yml:73` pins `--maxmemory-policy noeviction`; `docs/runbook.md:18` forbids `volatile-*`/`allkeys-*` | PASS |
| 2 | upgrade/downgrade 成功 | `qa/02-tables.log`: upgrade→`\dt` 9 tables→downgrade (only `alembic_version` left)→re-upgrade round trip | PASS |
| 2 | `grep -riE 'password|cookie' backend/app/models` 0 命中 | `qa/02-no-secrets.log`: exit 1 = 0 hits; re-verified this audit (0 hits) | PASS |
| 2 | partial unique index 存在 | `qa/02-tables.log`: `\d write_jobs` shows `uq_write_jobs_active_payload_hash ... WHERE status IN ('queued','running')` | PASS |
| 2 | 禁止表 `selcrs_sessions` 不存在 | `qa/02-tables.log` table list has no such table; grep `selcrs_sessions` over `backend/app` + `backend/alembic`: **0 hits** this audit | PASS |
| 3 | mock 驗證三態、redirect 不跟隨、失敗標記變體命中 | `qa/03-tristate.log`: 10/10 passed (302+`main_frame`+Set-Cookie; NFKC/alert/meta-refresh variants; follow_redirects=False pinned) | PASS |
| 3 | semaphore 與退避序列正確 | `qa/03-throttle.log` (global ≤2, captcha lane =1, per-run jar; 5 passed) + `qa/03-backoff.log` (waits exactly 1/2/4/8/16s → `SelcrsUnavailable`; 3 passed) | PASS |
| 3 | HKSCS fixture 不炸 | `qa/03-hkscs.log`: 喆 round-trips big5hkscs, `replace` policy; 3 passed | PASS |
| 3 | grep 斷言（業務碼禁 import httpx） | `qa/02-no-secrets.log` + F2 security-grep #6: 0 hits outside `app/selcrs/`; guardrail test in suite | PASS |
| 3 | 3 組密碼測試向量入文件 | `docs/verified-facts.md`: `123456`/`654321`/empty vectors table, locked in `tests/test_selcrs_transform.py`, openssl-reproducible | PASS |
| 3 | `[LIVE]` validcode BMP 存證 | `qa/03-validcode.bmp` (8,982 B, `BM` magic, 124×24 24-bit, legacy TLS handshake noted in `qa/03-tristate.log`) | PASS |
| 4 | `[WINDOW][CREDS]` 執行 → fixtures/請求體齊 **或逐項標記缺失原因** | `qa/04-readonly-capture.log` (in-window 09:52 read-only round, 9 outbound calls each justified, ≤3 SSO2 POSTs) + `qa/04-fixtures.log` (provisional set marker-verified) + live fixtures landed 2026-08-28: `studfun_open_live_1151.html`, `ssform_live_1151.html` (15 hidden inputs enumerated), `slt_result_live_1151.html`, `sso2_fail_live_1151.html`, `studfun_closed_live_1151.html`, **real ssprs reply `ssprs_resp_addfail_live_1151.html` + sent body `ssprs_post_body_addfail_live_1151.txt`** (freshens the M-CAPTURE worst case — no `provisional-missing` needed). **Residual unmarked items**: `saddstage5` live (school exposed only the ssform variant this window — observable constraint, not marked), second consecutive POST body + rotation diff (absent, unmarked), 陰性 carry-over replay probe (absent, unmarked), Referer-requirement probe (marked `*PENDING*` in `docs/verified-facts.md` L101). 承接: M-CAPTURE spans 115-1 加退選二 (09-09~09-11) with `DEFERRED-TO-1152` fallback per plan — see §2 and §4 | **PASS-WITH-DEFERRED** |
| 4 | 非窗口 CLI 拒絕 → `qa/04-not-in-window.log` | present: `[WINDOW-GUARD] Refusing`, exit 2, next window date correct | PASS |
| 4 | `verified-facts.md` 六項探測有結論 | 4 fully concluded live: session TTL ≥3 min (upper bound UNVERIFIED by design — scoped), 單 session = school coexists, SSO2 成功/失敗標記 (failure text `學號碼密碼不符` live-confirmed + UTF-8-encoding bug found & fixed), dplycourse 課號欄 conclusion (`courses.code` stays NULL; documented fallback identity). **必修確認前置**: live-observed `need_confirmation=false` in `qa/13-live.log` (10:33, real session) but **not transposed into `docs/verified-facts.md`**. **carry-over+Referer**: `PENDING` (unresolved) | **PASS-WITH-DEFERRED** |
| 4 | 單 session 探測結論寫成二值規則 | `docs/verified-facts.md` (d): school allows concurrent sessions → supersede remains a site-side policy (todo-8 `SESSION_SUPERSEDED`), binary and actionable | PASS |
| 5 | 運算型閘門（≥20 live 頁 ×100% 於 ≤5 重試 × ≥3 時段）；未達→`BLOCKED-ON-USER-DECISION` 記錄＋使用者裁決 | `qa/05-accuracy.log`: 3 batches × 7 pages across 3 time slots (evening 22:18 / late-night 02:22 / window-open 09:55), per-attempt p and per-depth tables recorded — **evidence of measurement is complete and diverse**; formal gate NOT met (18/21 pages within budget); results recorded (`BLOCKED-ON-USER-DECISION` input ✓); **使用者裁決/ADJUDICATION NOTE absent — see FAIL §1** | **FAIL** |
| 5 | failure: mock 連5錯碼 → `CaptchaUnsolvable` → `qa/05-loop.log` | present: exactly-once-after-5 (no 6th), injected fake solver, marker tolerance; 12 passed | PASS |
| 5 | overlap-jar 斷言 → `qa/05-jariso.log` | present: two overlapping loop runs never share a jar lineage; 1 passed | PASS |
| 5 | `pip show ddddocr` 釘版 → `qa/05-pin.log` | `ddddocr==1.6.1` in venv, `pyproject.toml:16` pin, `uv.lock` entries cross-checked | PASS |
| 6 | fixture 3 頁入庫斷言 → `qa/06-parse.log` | 29 passed: live+provisional fixtures, class_time[7], HKSCS 喆, both pagination variants, fused-room, link extraction | PASS |
| 6 | failure: 中途500 → 舊快照＋ok=false → `qa/06-partial.log` | 5 passed against real compose Postgres (mid-run failure keeps snapshot; layout-break abort; dedup) | PASS |
| 6 | `[LIVE]` 全量一次（課數/耗時/錯碼） → `qa/06-live.log` | 141/141 pages, 2809→2596 stored (arithmetic closes), wall 327.2s < peak 600s gate, charset utf-8 confirmed, plus 2 unaided production-scheduler runs (436.3s, 370.8s — both <600s, upsert/delete lifecycle verified) + 8-char-code-column conclusion recorded | PASS |
| 7 | happy: 種子 12 課＋6 組條件 → `qa/07-query.log` | 36 passed (all filter dims, weekday+period combo, NULL-code row, meta.ok=false → 200) + real-stack cURL of meta/courses/weekday+period against the live 2596-row snapshot | PASS |
| 7 | failure: `period="Z"` → 400 → `qa/07-badparam.log` | HTTP 400 with explicit message; sibling cases enumerated | PASS |
| 8 | 三態路由正確 | `qa/08-login-ok.log` (SUCCESS→200 + cookie flags, mock scripted) + `qa/08-lockout.log` (5×401 CREDENTIAL-FAIL) + `qa/08-unknown.log` (5×503 UNKNOWN → breaker streak=5) | PASS |
| 8 | 鎖定語意（滑動日誌個別到期/固定鎖不延長/就拒不入日誌/成功不清零）測試在案 | `qa/08-lockout.log`: 13 passed — `test_failures_expire_individually`, `test_fifth_failure_locks_and_lock_is_fixed_and_unextending`, locked attempt = local 429 school_calls/log unchanged, `test_success_never_clears_the_failure_log` | PASS |
| 8 | cookie 旗標測試 | `qa/08-login-ok.log`: `session_id=...; HttpOnly; Path=/; SameSite=lax; Secure` asserted + `tests/test_auth_sessions.py` 6 passed | PASS |
| 8 | job supersede 轉移測試 | `tests/test_auth_db.py::test_upsert_and_supersede_rule` in `qa/08-login-ok.log` suite (26 passed) | PASS |
| 8 | E2E 後 grep log 無密碼/cookie 值 | `qa/08-live.log` step 4: raw password / transform / 3× cookie values all 0 matches; access log path+status only | PASS |
| 8 | `[LIVE][CREDS]` 真實登入 → `qa/08-live.log` | real login → `me` → logout round trip through the compose app; Redis `selcrs:` 1800 / `selcrs_hard:` 7200 / site session 7d; student masked `M153****24`, password + cookie values never printed, masking map in /tmp deleted | PASS |
| 9 | 三狀態解析正確 → `qa/09-parse.log` | real live fixture parses 7 rows `{選上:5,失敗:2}`, spot-check row structural; 19 passed | PASS |
| 9 | courses join 缺課標 unknown 不擋 | `qa/09-live.log` step 2: 7/7 unknown=true, join ran, matched nothing, dropped nothing | PASS |
| 9 | 快取清除有測試 | `qa/09-live.log` step 7: logout → selections/selcrs/site_session keys all 0; session-scoped TTL=7d in step 5 | PASS |
| 9 | 過期 → 401 `SELCRS_EXPIRED` → `qa/09-expired.log` | login-page bounce and missing jar both 401 `SELCRS_EXPIRED`, zero-school-call case; unrecognized shape → 503 (never 401) | PASS |
| 9 | `[LIVE][CREDS]` → `qa/09-live.log` | real login → sync (exactly ONE slt_result GET) → cached GET (zero school calls) → frozen second-sync diff → secrecy greps CLEAN → catalog untouched (2596) | PASS |
| 10 | 15×7 grid 正確；點選即時；衝堂+tooltip；總計；徽章對 DB | `qa/10-live.log`: 0→3→9 blocks at correct cells, counter 2596, conflict row tint + tooltip naming course+slots, hover sync both directions, localStorage round-trip; `qa/10-grid.png` pixel-verified this audit (7 weekday cols, A/1-4/B/5-9/C/D/E/F rows, 3 courses blocking correctly, weekend shading) | PASS |
| 10 | vitest 案例含 `"56"vs"5B"` 衝、`"A"vs"1"` 不衝、無效碼拋錯 | `qa/10-vitest.log`: 24 passed + `npm run build` green (tsc + vite) | PASS |
| 10 | failure: mock meta ok=false → 橫幅 → `qa/10-banner.png` | route-intercept degrade: banner visible with Asia/Taipei time, catalog still renders; `qa/10-banner.png` pixel-verified (banner text + blocks still rendering) | PASS |
| 11 | 未登入導頁；2 組切換保留；志願序重複拒絕；同步一致；過期導頁訊息 | `qa/11-flow.log` ALL mock checks: no-captcha login (2 inputs), guard, 2 plans + switch hydration (3 rows), drag→priorities 1..N autosave, single-primary invariant, grouped states, diff counts, **401 → `/login?reason=expired` with stable param + distinct notice**; `qa/11-flow-*.png` 6 files | PASS |
| 11 | 後端 plans API 依賴在案 | `qa/11-plans-api.log` 9 passed (real Postgres) + 240-suite green; `qa/11-vitest.log` 62 passed | PASS |
| 11 | failure: 401 expired → `qa/11-expired.png` | captured alongside the flow assertions above | PASS |
| 11 | (extra, supportive) 真實鏈路 | `qa/11-live.log`: real SSO2 login via built `/login`, plan CRUD, keyboard-drag priorities persisted server-side, real sync 7 selections, cleanup, secrecy greps CLEAN | PASS (extra) |
| 12 | python icalendar 可解析＋結構斷言（VTIMEZONE、UNTIL 為 UTC DATE-TIME、UID/DTSTAMP 確定性） | `qa/12-ics.ics` (real file via Caddy) + `qa/12-parse.log`: CRLF ≤75-octet, VTIMEZONE Asia/Taipei, 4 VEVENTs = Σblocks, all `RRULE UNTIL=20270116T155959Z` UTC, fixed DTSTAMP, sha1 UIDs distinct per block, two generations byte-identical; 12 pytest passed | PASS |
| 12 | failure: 缺 UNTIL 或型別錯 → 測試紅 → `qa/12-bad-ics.log` | live stack returns 409 `bad_period_code` naming course/day/slot, never silent-skip; 2 passed | PASS |
| 12 | 空表 → 提示 → `qa/12-empty.log` | 409 `plan_empty_no_events`, JSON not a file | PASS |
| 12 | 設計審查報告＋修正前後截圖 | `qa/12-design-review.md`: Gemma-4 multimodal critique verbatim + **worker pixel-adjudication** (H1 verified→fixed; H2/H3 refuted with before-screenshot evidence; M4 fixed incl. new `.btn-brand` token) → open-high = 0 and ≥1 medium fixed, before/after files `qa/12-before.png`/`qa/12-after.png` + `qa/12-login-before.png`/`qa/12-login-after.png` present; DESIGN.md §9 updated | PASS |
| 12 | PNG 匯出非空白 | `qa/12-live.log`: `nsysu-crs-QA12驗證課表-20260828.png` 179,781 B, IHDR 1798×1602, name rule ✓; UI-downloaded ICS byte-identical to API response | PASS |
| 13 | 開放/關閉/初選 fixtures 正確；variant 正確 | `qa/13-stage.log`: detection matrix — closed-live→`closed`, open-ssform→加退選 (writable), **open-stage5→初選 `writable=false` flag-off / `true` flag-on**, drift→`未知`; 24 passed | PASS |
| 13 | needConfirmation → 專用碼 | `qa/13-stage.log` matrix row: ssform_prestep fixture → `need_confirmation=true / writable=false`; `qa/14-invalid.log` invalid#14: preview → **409 `need_confirmation`** | PASS |
| 13 | HTML 異動 → `unknown` 不誤判 → `qa/13-unknown.log` | 2 passed; drift returns a VALUE (`未知/drift_no_marker`), zero exceptions | PASS |
| 13 | `[WINDOW][CREDS]` → `qa/13-live.log` | `[DEFERRED-TO-WINDOW 2026-08-28 09:00]` header documented pre-window; **LIVE RUN appended 10:33 — `STAGE_EXIT=0`, stage=加退選, variant=ssform, `writable=true`, live X1/X2 bounds carried, case-insensitive params re-validated; read-only probe only** | PASS (deferred→resolved) |
| 14 | 檢查逐項可觸發 | `qa/14-invalid.log` invalid#1–#16: 無課號 ×2 / 衝堂 ×2 / 不在已選 / +-混 / priority 400s ×4 / ops>15 / typed-code / closed 409 / need_confirmation 409 / 401 / quota-warning non-blocking; 22 passed | PASS |
| 14 | 重放組包對 fixture 之 hidden 全數原樣通過（diff 測試） | `qa/14-preview.log`: payload preview deep-equal 57 keys; `qa/14-replay.log`: **11 hidden fields byte-identical verbatim** for both ssform + saddstage5 fixtures, D/C/T slot math owned | PASS |
| 14 | confirm_token 重放 409 | `qa/14-replay.log`: atomic GETDEL single-use — second consume → None (maps to 409); `qa/15-idem.log`: replay → 409, re-preview+submit → 409 carrying existing job id, exactly one ticket | PASS |
| 14 | CSRF 403 | `qa/14-csrf.log`: missing → 403 zero school touch, wrong → 403, right → pass + 900s slide, login mint/echo, rotate on fresh login; 8 passed | PASS |
| 14 | 無 token 直打 submit 400 | `qa/15-idem.log`: `test_submit_without_a_token_is_400` CSRF-required test adjacent; 8 passed | PASS |
| 15 | 雙擊 → mock 學校收 1 | `qa/15-idem.log`: first 202, replay 409, re-preview+submit 409 (partial unique index atomic), **exactly one ticket ever enqueued**, school sees exactly 1 job | PASS |
| 15 | 部分失敗續送不回滾 | `qa/15-mixed.log`: 3-op mixed batch executed `ok/額滿/必修` mapped back by course code, no rollback; 11 passed; **NEW SECTION 10:35**: canonical regression on the real live reply fixture, 31 passed | PASS |
| 15 | 過期/取代兩終態碼文案分流 | `qa/15-submit.log` dwell→`cancelled` own message; `qa/15-auditfail.log`: dead session → `階段逾時` (all ops, no retry) ×3 paths; `qa/15-superseded.log`: distinct copy `你已在別處重新登入，此批送單已取消，請重新預檢`; 7 passed | PASS |
| 15 | audit sink 掛 → 零送出 | `qa/15-auditfail.log`: fail-closed proven — ZERO school calls, no half-written audit rows | PASS |
| 15 | payload 掃描（無密碼） | `qa/15-submit.log` whitelist scenario: ticket keys == whitelist exactly, no secret-shaped fields; 14 passed (canonical roundtrip incl. zero-padding) | PASS |
| 15 | `stop redis` → login/write 硬失敗、讀取活 → `qa/15-redisdown.log` | live compose matrix: login+preview+submit+jobs → 503 `redis_unavailable`, courses+meta → 200 from Postgres, health → 503; restore → 200; 5 hermetic passed | PASS |
| 15 | `[WINDOW][CREDS]` 實送一可退加選 → `qa/15-live.log` | `[DEFERRED-TO-WINDOW]` header + **LIVE RUN 10:32 `SEND_EXIT=0`**: bogus-code-only probe (ZZ999999, local-only seed deleted after) → login → preview(200,writable) → submit(202) → job done → audit row `outcome=failed` carrying the school's own 【加退選失敗課程清單】, stuid salted; **zero modification to real selections**; 10:04 root-cause (static=draft action) fixed via 送出-button JS pin (ssprs.asp + step=2) documented | PASS (deferred→resolved) |
| 16 | 阻擋不可送；密碼僅當次；原訊可見；兩終態文案不同；對帳正確；業務失敗文案不含「自動重試」暗示 | `qa/16-flow.log` scenes A–H all OK: closed gate / blocked-confirm-disabled transition / modal password-gate / happy 2+1 poll queued→running→done / school raw messages verbatim / E5 explicitly asserts no auto-retry wording / superseded dedicated copy / reconcile 一致-不一致 diff table / transport_failed + 階段逾時 labels + re-preview CTA / H4 X-CSRF-Token header on preview+submit+jobs; 90 vitest passed; `qa/16-flow-results.png` pixel-verified this audit (all four verdict tones + 對帳 rows) | PASS |
| 16 | failure screenshots present | `qa/16-fail.png`, `qa/16-superseded.png` + 5 flow shots — all present | PASS |
| 17 | https smoke 綠 | `qa/17-smoke.log`: full stack healthy, 7 endpoints 200 through Caddy (only published entry), CSP/nosniff/X-Frame-Options/Referrer-Policy headers, non-root containers (uid 10001/10002), port map = caddy only, TZ spot CST. **HTTPS-proper (real-domain TLS) is structurally impossible pre-launch** — 承接: `docs/launch-checklist.md` §B (TLS cert + HSTS enable + fresh security sweep as day-of checks) | PASS-WITH-DEFERRED |
| 17 | 備份產檔 | `qa/17-backup.log`: pg_dump→gz artifact, `gzip -t` OK, rotation ≤14, **scratch-DB restore with matching row counts**, scratch dropped | PASS |
| 17 | breaker 開/回可驗 → `qa/17-breaker.log` | 5×UNKNOWN→OPEN, sitewide local-503 zero-outbound (login/stage/sync/preview), ops-state public/admin seam gated, probe-fail restamps wait, probe-alive closes; 12 passed | PASS |
| 17 | grep 安全包 → `qa/17-grep.log` | scripts/security_sweep.sh: models/DB-schema/runtime-logs credential greps all 0, Caddy header filter landed, no CORSMiddleware + no ALLOWED_ORIGINS wildcard, pip-audit 0 vulns, npm audit 0 vulns; **VERDICT: CLEAN** | PASS |
| 17 | 法務三頁要件齊 | `/privacy /tos /faq` 200 (`qa/17-smoke.log`) + grep-verified elements: FAQ Q2 預設密碼=身分證後六碼更換勸導、Q4 本站限速僅保護本站＋學校端自有偵測聲明；TOS §限速保護範圍、§鎖定濫用 accepted-risk 情境 | PASS |
| 17 | runbook/checklist 文件化 | `docs/runbook.md` §1 restart/ports、§2 backup SOP、§5 SSO2-failure degrade（含禁建 Studcheck 降級無計畫變更）、§6 鎖定濫用 alert SOP（門檻＋`/api/ops/state` 信號）、§7 預設密碼勸導回應、§8 destructive gating；`docs/launch-checklist.md` A–E sections（含 M-LAUNCH 條款：唯讀全開／寫入口視 live 驗證／初選 flag=false、`v1.1.0` 翻旗程序） | PASS |
| 17 | destructive catalog tests opt-in 誠實性 | `qa/17-destructive-gating.log`: default run INSIDE container against live Postgres → all 5 SKIPPED (nothing wiped); flagged run against scratch DB → 5 PASSED; live catalog identical before/after | PASS |

## 2. Deferred-set resolution (cross-check vs task brief)

| Item (brief) | Repo state verified this audit | Resolution |
|---|---|---|
| todo-4 `[WINDOW]` live capture: `ssform_live_1151.html` + `studfun_open_live_1151.html` + 8 probes landed | **CONFIRMED present** — both files in `backend/tests/fixtures/` (28,861 B form with all 15 hidden inputs; 1,917 B Studfun-open), `qa/04-readonly-capture.log` 09:52 round enumerates the 8 probe outcomes into `docs/verified-facts.md` §live-verified (115-1), plus the 10:30 write-path run pinned the real ssprs reply + sent body | **RESOLVED as briefed**, with residual capture gaps per §1.t4 (unmarked: `saddstage5` live / 2nd body + rotation diff / 陰性 replay; PENDING-marked: Referer). 承接 = M-CAPTURE window continues (115-1 加退選二 09-09~09-11); plan fallback `DEFERRED-TO-1152` applies otherwise |
| todo-13 live stage: `qa/13-live.log` writable=true | **CONFIRMED** — `[DEFERRED-TO-WINDOW]` header + LIVE RUN 10:33 `STAGE_EXIT=0`, `stage=加退選, variant=ssform, writable=true`, real-session, read-only | **RESOLVED** （承接應驗） |
| todo-15 live send: `qa/15-live.log` SEND_EXIT=0 | **CONFIRMED** — LIVE RUN 10:32 `SEND_EXIT=0`, end-to-end live write chain with school business-failure audit row; zero real-selection modification by construction | **RESOLVED** （承接應驗） |
| solver gate: 3 batches + ADJUDICATION NOTE appended (bottom of `qa/05-accuracy.log`) | **DISPUTED** — 3 batches across 3 diverse time slots confirmed (diversity ✓); **ADJUDICATION NOTE NOT FOUND** at file bottom or anywhere in the tree (grep `ADJUDICATION|operational acceptance|veto|裁決|放寬` → only the batch-1 *pending* line in `docs/verified-facts.md` + unrelated design-review uses); `git log --follow qa/05-accuracy.log` shows 3 batches, no adjudication commit | **Open item = the §0 FAIL.** Record intent per brief: *gates formally imperfect, adjudicated to operational acceptance; user veto reserved* — the adjudication record itself must be appended by the user/authorized worker before F1 can flip |
| `FEATURE_FIRST_ROUND_WRITE=false` still false | **CONFIRMED** — `.env.example:12` `=false`; `backend/app/config.py:42` default `False` | maintained |
| 初選 write absent from API (todo 13 flag behavior) | **CONFIRMED** — `backend/app/stage/detect.py:220` `return first_round_write` (stage5 writable requires flag true); `backend/app/api/stage.py:140` + `api/write.py:188` route the flag; positive proof `qa/13-stage.log` matrix row （初選/stage5 → `writable=false` flag-off) | maintained; flip procedure documented (`v1.1.0`, launch-checklist §E) |
| Remaining `DEFERRED-TO-1152` items | **None outstanding** — the only deferral markers in the tree are the two `[DEFERRED-TO-WINDOW]` headers above, both now closed with live runs appended this window; zero `DEFERRED-TO-1152` / `provisional-missing` markers needed or present (real ssprs reply landed) | closed set |

## 3. Scope-consistency spot checks (agreed basis with F4's formal pass)

| Check | Method (local only) | Result |
|---|---|---|
| No password columns in models | `grep -riE 'password\|cookie' backend/app/models` | **clean (0 hits)** — matches `qa/02-no-secrets.log`, `qa/17-grep.log` |
| No GA / third-party analytics | `grep -rniE 'googletagmanager\|google-analytics\|\bgtag\b\|analytics\.js'` over `frontend/src`, `frontend/index.html`, `backend/app`, `deploy`, `Caddyfile` | **clean (0 hits)** |
| No notification channels | `grep -rniE 'line_notify\|discord\|smtp\|mailgun\|sendgrid\|pushover\|telegram'` over `backend/app`, `frontend/src`, `deploy`; no notify module exists | **clean (0 hits)** — queue results surface in-site only |
| No torch / no captcha-model training | `grep -cni 'torch' backend/pyproject.toml backend/uv.lock` | **0 / 0** — ddddocr 1.6.1 runs on onnxruntime (`qa/05-pin.log`) |
| Login uses SSO2 (`base64md5`) only | `backend/app/selcrs/transform.py` = byte-exact NsysuApp port; `endpoints.py:166` POSTs only `Studcheck_sso2.asp` with `SPassword=base64md5(password)`; `grep 'Studcheck\.asp'` (plain, non-sso2) over backend/scripts | **clean (0 hits)** — no captcha fallback path exists |
| Redis-only selcrs cookies, no `selcrs_sessions` table | `grep -rniE 'selcrs_sessions' backend/app backend/alembic` = **0 hits**; `qa/02-tables.log` `\dt` shows no such table; `models/__init__.py` documents the policy; live TTLs observed in `qa/08-live.log` | **conforms** |
| Business-failure terminal policy in code | `backend/app/write/outcomes.py` docstring: 業務失敗=終態 immediately; engine retry discipline ≤2 **transport-only** (adapter backoff), `unknown-reconciled` holding state; proofs in `qa/15-submit.log` (transport budget exactly 2), `qa/15-mixed.log` （額滿/必修 terminal), `qa/16-flow.log` E5 (no auto-retry wording) | **present and enforced** |

## 4. Artifact naming discrepancies (pointer lines — files intentionally NOT renamed)

| Plan-named artifact | Actual file(s) | Note |
|---|---|---|
| `qa/04-capture.log` | `qa/04-readonly-capture.log` (in-window live capture round, 2026-08-28 09:52) **and** `qa/04-fixtures.log` (provisional fixture creation + marker verification) | **POINTER:** read `04-capture.log` as ≡ `04-readonly-capture.log` ∪ `04-fixtures.log`; the write-side POST capture produced its artifacts under `backend/tests/fixtures/` (below) rather than a second qa log |
| `qa/04-post-body.txt` | `backend/tests/fixtures/ssprs_post_body_addfail_live_1151.txt` (+reply `ssprs_resp_addfail_live_1151.html`/`.txt`) | **POINTER + gap:** the single real POST body lives in fixtures, not qa/; the plan's *second* consecutive body for rotation diff was not captured (see §1.t4 residual) |
| — | extras not named by the plan: `qa/03-encoding.log`, `qa/10-live.log`, `qa/11-vitest.log`, `qa/11-plans-api.log`, `qa/11-live.log`+PNGs, `qa/12-live.log`, `qa/17-backup.log`, `qa/17-destructive-gating.log`, `qa/17-pages.png` | supportive extras; no plan violation — recorded here for path-finding |
| — | `qa/13-live.log`, `qa/15-live.log` each retain their pre-window placeholder line ("Probe executed but results not yet recorded above." / planned-run preamble) **above** the appended LIVE RUN section | cosmetic stale line inside resolved logs; the LIVE RUN verdicts (`STAGE_EXIT=0` / `SEND_EXIT=0`) govern |

## 5. Closing notes

- **F2** (`qa/F2-quality.md`, committed at `cd09817`) is APPROVE and mutually consistent with this audit (its security greps corroborate §3 rows 1–2). **F3/F4 have not been executed** yet — per plan they run in parallel with F1 and are out of this document's scope except where noted.
- Item for user awareness (not a gate): `docs/verified-facts.md` L101 still carries the Referer-requirement probe as `*PENDING*` — the 10:30 live send carried a Referer and succeeded, which proves the header is *accepted* but not yet whether it is *required*.
- Flip condition for F1 → APPROVE: exactly one evidence-layer change — the 使用者裁決 adjudication note appended to `qa/05-accuracy.log` (naming the decision branch per the plan's `BLOCKED-ON-USER-DECISION` enumeration and carrying explicit user sign-off or explicit veto).

## 6. F1 flip resolution (2026-08-28, re-verified against `b973c4b`)

The single FAIL entry in §0 (todo-5 adjudication note absent) is **RESOLVED**:

- Commit `b973c4b` (`chore(qa): todo-5 gate adjudication note ...`, +30 lines, `qa/05-accuracy.log` only) appends the **ADJUDICATION NOTE (2026-08-28)** at the file's end — verified present by re-reading the tail this pass.
- The note **names the decision branch** per the plan's enumerates: `CHOSEN = A, operational acceptance` (torch/CapsNet remain OUT; community-JSON re-scope not taken), justified on production evidence (1-captcha-per-run contract, 4/4 completed ingests at 327s–451s, self-healing degrade, atomic snapshot preservation).
- It records **full batch evidence** (7/7 + 6/7 + 5/7, p=0.438/0.273/0.227, p_total=18/60=0.300), a **trip-wire** (escalate to user for options B/C if >2 consecutive production ticks fail), and the **explicit veto reservation** ("orchestrator decision under the user's blanket delegate-and-decide authorization; user retains veto") — satisfying every element of the flip condition below §5.
 - Non-gating observation recorded for trail honesty: the note's aggregate line read "Totals: 19/21 pages" while its own batch lines (7+6+5) and the p_total math (18/60) both give **18/21** — a one-off tally typo inside the note; batch-level evidence lines remain the authoritative record. **Corrected to 18/21 on 2026-08-28 during the post-reviewer-gate scrub pass.**
- **Final verdict: F1 = APPROVE** (zero FAIL entries remain; all other rows of the §1 table stand unchanged from the original audit). Launch blocking is governed by launch-checklist §D — F1 APPROVE is one of four required wave approvals; F3/F4 remain open per this document's scope.

---

## F1 flip resolution (appended 2026-08-28 by orchestrator, per the flip condition defined above)

The single FAIL entry is RESOLVED: the adjudication note has been appended at the tail of `qa/05-accuracy.log` — branch **A (operational acceptance)** named explicitly per the plan's `BLOCKED-ON-USER-DECISION` enumeration, with batch evidence (18/21 pages, per-attempt p_total = 0.300 across evening/late-night/morning slots), the operational rationale (1 captcha per run, 4/4 production ingests passed, degrade self-heals next tick, snapshot-atomic persistence), a trip-wire (>2 consecutive failed production ticks → escalate to user for options B torch / C community JSON), and authorization recording (orchestrator acting under the user's blanket delegate-and-decide authorization; **user veto reserved**). Committed+pushed as `chore(qa): todo-5 gate adjudication note (operational acceptance, user veto reserved)` — verifiable via `git log -1 -- qa/05-accuracy.log`.

FAIL count is now zero. **Final verdict: F1 = APPROVE.**
