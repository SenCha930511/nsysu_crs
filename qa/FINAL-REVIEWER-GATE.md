# FINAL REVIEWER GATE — nsysu-course-wrapper

- Gate executed: 2026-08-28 (Asia/Taipei), read-only, independent of the F1–F4 workers.
- Tree under review: `main` @ `39beccb` (working tree clean; `HEAD == origin/main`, verified by rev-parse).
- Method: re-read the plan's final-verification section + all 17 todo acceptance criteria; re-read
  `qa/F1-compliance.md` / `qa/F2-quality.md` / `qa/F4-scope.md` end-to-end; skimmed
  `qa/F3-manual/transcript.md` + per-todo logs named by the brief (`03-tristate`, `05-accuracy`
  incl. ADJUDICATION NOTE tail, `06-live`, `08-login-ok`, `15-live` SEND_EXIT transcript,
  `17-smoke` / `17-grep` / `17-breaker` / `17-backup` / `17-destructive-gating`, `12-live`);
  re-ran both suites and the lint/type gates myself; sample-checked claims against code,
  fixtures and cross-file consistency; applied the plan's final checklist terms one by one.
- No live network calls to the school; `/tmp/ulw-creds.env` never opened.

---

## 1. Suite re-runs (this gate, current tree)

```
$ cd backend && uv run pytest
327 passed, 99 skipped, 67 warnings in 2.11s

$ cd frontend && CI=1 npx vitest run
 Test Files  9 passed (9)
      Tests  107 passed (107)
```

Observed counts match the documented expectations exactly (327/99/0 and 107/107).
Skip-reason audit re-run (`pytest -rs`): every skip is one of exactly two sanctioned
reasons — 94× `compose Postgres unreachable` (DB-backed tests, local posture) and 5×
destructive opt-in in `tests/test_catalog_db.py`. Zero unexpected skips.

Additional gate re-runs (same tree): `uv run ruff check .` → All checks passed;
`uv run mypy` → 0 issues in 82 source files; `npx tsc --noEmit` → green.
(`git diff cd09817..HEAD -- backend/` is empty, so F2's backend gates remain valid;
the post-F2 frontend rewrite `14eb1fb` is covered by the vitest + tsc re-runs above.)

## 2. F1–F4 documents — correctness assessment

- **F1 (`qa/F1-compliance.md` + flip addendum)**: sound. Original FAIL (todo-5 adjudication
  note absent) was accurate skepticism; the flip condition was satisfiable via `b973c4b`,
  and this gate re-verified the ADJUDICATION NOTE tail in `qa/05-accuracy.log` (branch A
  named, batch evidence, trip-wire, veto reservation). F1 also honestly recorded the
  note's internal 19/21 vs 18/21 tally typo as non-gating.
- **F2 (`qa/F2-quality.md`)**: sound. ruff 48→0 and mypy 30→0 dispositions are documented
  per finding; the 94+5 skip decomposition is exactly what this gate observed; all six
  security greps re-verify on the current tree.
- **F3 (`qa/F3-manual/transcript.md`)**: sound. Step-by-step in-window actions are
  consistent with `qa/15-live.log` (SEND_EXIT=0) and the cleanup state it claims;
  the variant degrade drill (redis stop) matches `qa/15-redisdown.log` semantics.
- **F4 (`qa/F4-scope.md`)**: **one disqualifying defect** (grep-command lines embed the raw
  student id — see Verdict / Blocking item 1). All other 9 rows + 附掃 re-verify as claimed.

## 3. Sample checks executed (claim ↔ artifact/code)

1. Live fixtures exist: `studfun_open_live_1151.html`, `ssform_live_1151.html`,
   `sso2_fail_live_1151.html`, `slt_result_live_1151.html`, `studfun_closed_live_1151.html`,
   `dply_page_live_1151.html`, `ssprs_resp_addfail_live_1151.html`,
   `ssprs_post_body_addfail_live_1151.txt` — all present in `backend/tests/fixtures/`.
2. Write-flow `step=2` injection: `backend/app/write/engine.py:220` (`payload["step"] =
   submit_step`) + `backend/app/write/payload.py:121` (`_SUBMIT_ACTION_RE` pinning
   `f1.action='ssprs.asp'` / `saddstage5prs.asp`) — the live-verified root-cause fix is in code.
3. `grep -riE 'password|cookie' backend/app/models` → 0 hits (exit 1), matching F1/F2.
4. ICS RFC-5545 claims: `qa/12-ics.ics` contains 4× `UNTIL=20270116T155959Z` and
   `UID:…@nsysu-course-wrapper` — matches F1/F3 (4 VEVENTs, UTC DATE-TIME, deterministic UIDs).
5. `08-login-ok.log` internal consistency: 26 items collected / 26 passed, including the
   exact lockout-semantics tests F1 cites by name.
6. 初選 three-layer lock: `.env.example:12` `FEATURE_FIRST_ROUND_WRITE=false` +
   `backend/app/config.py:42` default `False` + `backend/app/stage/detect.py` `is_writable`
   returning `first_round_write` for `STAGE_FIRST_ROUND`; UI blocked with the
   「初選志願代送尚未開放」 copy (`WritePage.tsx:172`) and preview gated server-side
   (`write.py:188`).
7. 2596-row ingest arithmetic: `qa/06-live.log` (2809 − 11 − 202 = 2596, 141/141 pages,
   327.2s < 600s peak gate) is internally closed; two unaided production runs recorded.

## 4. Plan checklist terms applied

- **Deferral 承接** — COMPLETE. Only two `[DEFERRED-TO-WINDOW]` markers ever existed
  (`qa/13-live.log`, `qa/15-live.log`); both resolved with in-window live runs appended
  (STAGE_EXIT=0 10:33; SEND_EXIT=0 10:32). Zero outstanding `DEFERRED-TO-1152` /
  `provisional-missing` markers. Residual capture gaps (saddstage5 live, 2nd POST-body
  rotation diff, 陰性 replay probe, Referer-necessity `*PENDING*`) carry a named承接:
  M-CAPTURE spans 115-1 加退選二 (09-09~09-11), fallback `DEFERRED-TO-1152` per the plan's
  milestone clause — legitimate.
- **初選 flag OFF + UI blocked** — MET (§3 check 6; F4 row 4 corroborates; no independent
  first-round route exists).
- **Zero user-account writes except bogus probes** — MET. The only school-side write in
  every live artifact is the add of nonexistent `ZZ999999`; `qa/15-live.log` and F3 both
  show the school's own batch rejection 【加退選失敗課程清單】 and reconcile returning
  {選上:5} unchanged before/after.
- **Creds masking in all artifacts** — **NOT MET** (see Blocking item 1): the raw 8-digit
  student number (masked form `M153****24`) appears literally twice inside
  `qa/F4-scope.md` (the document's own grep-command lines, committed at `39beccb` and
  pushed); `git log --all -S` consequently finds that commit. F4 Row 10's claim
  ("live 紀錄一律遮蔽；歷史零命中") falsifies itself the moment it was committed.
  Everywhere else the convention holds (logs use `M153****24`; `M153000024` in
  `08-login-ok.log` is an explicitly-labelled mock constant; `write_audit` carries a
  salted, truncated hash).
- **Git coherence** — MET. 30 commits tell the 17-todo + F-wave story in dependency order
  (W0 1–4 → A 5–11 → B 12–17 → tooling/fixes → F1 flip → F3 → Gemini-redo+repair → F4);
  tree clean, `origin/main` synchronized.

## 5. Security / hygiene findings

- BLOCKER (item 1 below): raw student id committed in `qa/F4-scope.md` — PII of the
  operator account now lives in tree + history + remote; contradicts the plan's masking
  convention and F4's own Row 10 evidence claim.
- No other credential-shaped material found in tree: no password/cookie columns or values,
  no real cookie values in any log, no `selcrs_sessions` table, no GA/notify/torch /
  Studcheck(non-sso2) paths (F2/F4 greps reproduced).
- Google Fonts `<link>` third-party request is a documented user-decision exception
  (`qa/ui-redo-review.md`), not a tracker.

## 6. Residual risks independently identified (non-blocking)

- **R1 (top residual)**: on QA day ~08:52–10:0x the live DB was wiped to
  `courses=1, ingest_runs=1, write_jobs=0` — Postgres was recreated during qa-12 setup
  (self-documented in `qa/12-live.log` lines 41–46) and a thin fabricated state
  (fake-good `ingest_runs` row with `rows=1` finished at 08:52:22) sat as live meta.
  Consequences: (a) the backup/restore "matching row counts" proof at
  `qa/17-backup.log` was exercised against essentially an empty DB — mechanism proven,
  volume-fidelity not; recommend re-running `scripts/backup.sh` + scratch restore against
  the full 2596-row snapshot before M-LAUNCH (one command, cheap); (b) F1 cites
  `qa/17-smoke.log` as healthy while the same file's own meta body reads
  `"row_count":1` — no audit noticed the cross-file inconsistency (this gate did);
  (c) the catalog self-healed per design at the next ingest tick (F3 confirms 2596 at
  11:45), so the plan's degrade/recovery story is ultimately intact.
- **R2**: `docs/verified-facts.md` carries stale markers — the solver section still reads
  "gate-risk pending … user/decision branch" (never closed after the adjudication note
  landed), and the SSO2-failure bullet still marks `sso2_fail_*.html *PENDING*` though
  section (f) CONFIRMED it; the todo-4 Referer `*PENDING*` is honestly待承接 (R-list of
  M-CAPTURE, 09-09 window). Also F1's noted gap: live-observed `need_confirmation=false`
  not transposed. Documentation-only; no behavioral risk.
- **R3**: adjudication-note tally typo (19/21 vs its own 18/21 batch lines), already
  recorded by F1 as non-gating; suggest a one-line erratum on next touch.
- **R4 (closed)**: qa/12-live's transient 500 (asyncpg `InterfaceError` after Postgres
  recreation) is addressed — `backend/app/db.py:39` now sets `pool_pre_ping=True`
  (todo-17 hardening present in tree).
- **R5**: v1.0.0 tag not yet cut (launch-checklist §D gates M-LAUNCH on the tag); expected
  at this stage, not a defect.

## 7. Verdict

**CHANGES-REQUESTED** — a single blocking item; everything else is APPROVE-grade.

Blocking fixes (numbered by severity):

1. **Scrub the raw student id from `qa/F4-scope.md`** (rewrite the two grep-command lines
   to reference the masked form / a variable instead of the literal digits), commit and
   push. Tree-level cleanliness is achievable immediately. The id will remain in git
   history at `39beccb`; the history remedy (force-push rewrite of `main` vs a recorded
   user acceptance of the residual) is a user decision the gate cannot make — recommend
   the rewrite if the repo will ever be made public, otherwise record the acceptance
   alongside the erratum file.

Non-blocking follow-ups recommended before M-LAUNCH (not gate conditions):

- Re-run backup+scratch-restore against the true 2596-row snapshot (R1a).
- Close the `docs/verified-facts.md` stale/pending markers (R2) and append the 19/21
  erratum line to `qa/05-accuracy.log` (R3).
- Complete M-CAPTURE residual probes in the 加退選二 window (Referer necessity,
  陰性 replay, 2nd-body rotation diff, saddstage5 capture) as承接 per plan.

Once blocking item 1 lands, this gate may flip to **APPROVE** on the tree state alone
(no other re-verification is required — suites and greps above were run against the
current tree minus one documentation line).
