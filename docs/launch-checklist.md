# Launch Checklist — 115-2 單次公開上線（M-LAUNCH）

Per the plan milestone terms (`.omo/plans/nsysu-course-wrapper.md`, Execution strategy → 里程碑 + Todo 17): single public launch before the 115-2 初選 window (tentative 2027-01-29), after M-WB (todos 12–17) and the F1–F4 verification wave all APPROVE. **No launch while any F-wave is not APPROVE or any box below is unticked.**

## A. Feature-entry state (milestone terms — non-negotiable)

- [ ] **Read-only features fully open**: course browsing/filters, timetable, conflict/credit checks, quota badges, multi-plan + 志願序, ICS/PNG export, selections sync — all on.
- [ ] **加退選 write entrance gated on live verification**: OFF unless the `[WINDOW][CREDS]` live submission (plan todo 15 `qa/15-live.log`) has been completed; otherwise the write entrance stays closed with the visible notice 「待 115-2 加退選窗口驗證後 v1.1.0 開放」. If the capture milestone M-CAPTURE slipped, this box defaults to OFF.
- [ ] **初選志願 write flag**: `FEATURE_FIRST_ROUND_WRITE=false` in `.env` — unconditionally, until the 115-2 加退選 window live-verifies it (release `v1.1.0` documents the flip).
- [ ] Write-flow dusk behavior verified on the deployed instance: stage closed ⇒ preview 409 `stage_unavailable` copy visible in `/write` UI.

## B. Stack health (day-of checks, ~30 min)

- [ ] `docker compose -f deploy/docker-compose.yml ps` → all `healthy`; `curl -sf http://localhost/api/health` → `ok`.
- [ ] Security headers present through Caddy: `curl -sI https://<domain>/` shows CSP/nosniff/`X-Frame-Options: DENY`/`Referrer-Policy`; after HTTPS smoke, enable HSTS (uncomment the prepared line in `deploy/Caddyfile`, re-up caddy).
- [ ] `GET /api/ops/state` → `closed`; gated read with `X-App-Secret` shows `streak:0`.
- [ ] TLS: Caddy obtained + renewed certs (only with the real public domain set as the site address).
- [ ] Backup schedule installed on the host (`docs/runbook.md` §2 cron line) AND one manual `scripts/backup.sh` just ran; artifact restore-verified once (scratch DB counts).
- [ ] `scripts/security_sweep.sh` run fresh: `qa/17-grep.log` verdict CLEAN (regenerate and attach to the release record).
- [ ] npm `frontend/dist` rebuilt with this checkout; no DIFF between deployed bundle hash and `npm run build` output hash list.

## C. Content & legal readiness

- [ ] `/privacy`, `/tos`, `/faq` reachable and readable on the deployed domain (footer links work): 非官方聲明、密碼零落盤＋selcrs cookie Redis 短 TTL、PII 最小化與稽核生命週期（90d→去識別 gz→1y→刪）、預設密碼＝身分證後六碼勸導、本站限速僅保護本站＋學校端暴力風險聲明、鎖定濫用監測聲明、資料來源、聯絡管道 — the 聯絡管道 placeholder replaced with the real channel BEFORE launch.
- [ ] Legal pages re-screenshotted after replacement (repeat of `qa/17-pages.png` flow).
- [ ] Runbook handoff done: restart/restore/window-precheck/school-block/SSO2-fail/鎖定濫用 SOP/env-knob table read by the on-call.

## D. Wave-0–B regressions & F-wave

- [ ] Full backend suite green in-container (incl. DB-backed API suites); destructive catalog tests run flagged ONCE against a scratch DB (see `docs/runbook.md` §8) and stay SKIPPED by default.
- [ ] Frontend `npm run test` + `npm run build` green.
- [ ] F1（計畫符合性 `qa/F1-compliance.md`）APPROVE；F2（品質 `qa/F2-quality.md`）APPROVE；F3（端到端 `qa/F3-manual/`）PASS 或 `PASS-WITH-DEFERRED-WRITE`（此時 A-項寫入入口必須維持關閉並明示未驗證）；F4（範圍保真 `qa/F4-scope.md`）APPROVE。
- [ ] Tag `v1.0.0` on `main` after all APPROVE; M-LAUNCH executes from that tag, not from a floating main.

## E. Post-launch (first week)

- [ ] Daily: `lockouts` totals + breaker state reviewed (SOP: `docs/runbook.md` §6 spike response).
- [ ] Daily: backup archive present + ≤14 files.
- [ ] Window-precheck re-run before the first live 115-2 write window; if the deferred write live verification succeeds, cut `v1.1.0` and flip `FEATURE_FIRST_ROUND_WRITE=true` in the same release commit.
