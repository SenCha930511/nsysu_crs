# F4 — 範圍保真 (Scope Fidelity) audit

- Date: 2026-08-28 (Asia/Taipei), audited tree at `14eb1fb` (Gemini UI pass + orchestrator fixes).
- Audit source: `.omo/plans/nsysu-course-wrapper.md` — Scope **OUT (Must-NOT-Have)** lines + F4 row
  ("任一 OUT 出現=不通過：DB 或 log 出現 password/cookie 欄位或值、推播、GA、torch、Studcheck
  路徑、無 flag 之初選送出、業務失敗自動重試").
- Method: local grep / config / file-read assertions only. **Zero live network calls made by this audit.**
- Context: F1 APPROVE (`8b6b412`+flip `57f3694`), F2 APPROVE (`cd09817`, security greps cleaned),
  F3 PASS (`20aad19`); Gemini UI pass `14eb1fb` reviewed in `qa/ui-redo-review.md` — all greps below
  re-run against the CURRENT tree.

## Verdict summary

| # | OUT row (plan) | Verdict |
|---|---|---|
| 1 | 不埋 GA 或任何第三方分析 / 無遠端遙測 | **PASS** (+1 DOCUMENTED-EXCEPTION: Google Fonts &lt;link&gt;) |
| 2 | 不存任何形態密碼；selcrs cookie 不寫 Postgres/log；無 selcrs_sessions 表 | **PASS** |
| 3 | 密碼不出現於任何 runtime 留存路徑（含前端 storage） | **PASS** |
| 4 | `FEATURE_FIRST_ROUND_WRITE` 預設關閉；無無-flag 初選送出 | **PASS** |
| 5 | 不自動搶課；無背景自動送單 | **PASS** |
| 6 | 無 auto-update / 無對外 telemetry | **PASS** (+same Fonts exception) |
| 7 | 無碼行為：01/03 零臆造、04/05/06-assist 缺席、無「保證加選成功」字樣 | **PASS** |
| 8 | 視窗凍結：無排程寫入；/api/write/* 由 stage 閘門硬擋 | **PASS** |
| 9 | 危險按鈕現實性：初選 UI 封鎖、無真退毒按鈕、live 僅 ZZ999999 探針 | **PASS** |
| 10 | Repo 衛生：已知憑證 pattern 零命中（檔案+歷史）、.omo gitignored、憑證 env 在 repo 外 | **PASS** |
| — | F4 附掃：無推播、無 torch、無 Studcheck.asp 路徑、業務失敗不自動重試 | **PASS** |

**F4 = APPROVE.** 所有 OUT 條目均以當前樹上證據證明缺席；唯一對外第三方請求（Google Fonts）
有既存書面例外紀錄（`qa/ui-redo-review.md`），非新發現、非追蹤器。

---

## Row 1 — 不埋 GA / 追蹤 / 遠端分析

```console
$ grep -rinE 'google-analytics|googletagmanager|gtag|\bgtm\b|mixpanel|\bsegment\b|sentry|hotjar|clarity|facebook-pixel|amplitude|plausible|umami|matomo' frontend/src frontend/index.html backend/app backend/scripts scripts deploy
backend/app/write/canonical.py:80-95:  "segment" = canonical-string partition variable (本機字串處理，非 Segment SDK)
scripts/security_sweep.sh:10,67-77:  "SENTINEL"/"sentry" = 自造哨兵字串 SWEEP17SENTRY，用來證明 log 無憑證（非 Sentry SDK）
$ grep backend/pyproject.toml -> 無 sentry-sdk 等依賴 (DEPS_EXIT=1)
```

零追蹤器 SDK / snippet / endpoint 命中。兩處文字碰撞皆為無關語義（canonical 分段變數、
安全掃腳本的哨兵字串）。

**DOCUMENTED-EXCEPTION** — `frontend/index.html:7-12`：

```html
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@500;600;700;800&family=Plus+Jakarta+Sans:...&display=swap" rel="stylesheet" />
```

Google Fonts 靜態樣式請求（非 JS、非追蹤器），已由 `qa/ui-redo-review.md`
（"Noted, left for user to decide — fonts aren't trackers; offline dev falls back to system stack"）
書面記錄為使用者裁決保留項。非 FAIL。

## Row 2 — DB/Schema 無密碼/cookie 欄位；selcrs session 僅 Redis；CSRF 不寫 DB

```console
$ grep -rinE 'password|cookie' backend/app/models backend/alembic
(零命中, EXIT=1)

$ grep -rin 'selcrs_sessions' <tracked 非 qa 檔>
backend/tests/test_models.py:27,29:  # 反向斷言: exactly the 8 planned tables ... no selcrs_sessions
  assert "selcrs_sessions" not in Base.metadata.tables
docs/architecture.md:15: There is intentionally **no `selcrs_sessions` table**.
```

`selcrs_sessions` 僅出現在「證明其不存在」的測試斷言與文件敘述中，無建表碼、無 migration。

- Redis-only selcrs：`backend/app/auth/sessions.py:9,36` — `selcrs:{session_id}` key under
  SLIDING/HARD TTL；`backend/app/models/__init__.py:5` 註明 selcrs cookie 只進 Redis。
- CSRF 不寫 DB：`backend/app/write/csrf.py` docstring — double-submit cookie vs
  `X-CSRF-Token` header（`hmac.compare_digest`），"Server-side storage is not needed …
  The token never enters logs, Postgres, or any response beyond that one login body."
  `grep csrf backend/app/models` → 零欄位。

**PASS.**

## Row 3 — 密碼不落地（任何 runtime 路徑）

```console
$ grep -rn 'password\|Password' frontend/src
僅: LoginPage.tsx:16,105-130 (React useState, autoComplete=current-password, 送出後頁面導離)
    WritePage.tsx:475,489-492,562-571,1002-1007 (ConfirmModal 當次使用)
    api.ts:262-266 (login body) / api.ts:435-440 (submit body) — 僅 HTTP body 傳遞
    writeOps.ts:303-312 (comment: "never stored")

$ grep -rinE 'localStorage|sessionStorage' frontend/src
selection.tsx:  存課表選取/快取 (課程資料，非憑證)
plansSync.tsx:  存 active plan id
auth.tsx:28-42: sessionStorage 僅存 CSRF token echo (login response body 通道)
→ 無任何密碼寫入 web storage
```

WritePage modal 密碼歸零（14eb1fb 修復，**當前樹在案**）— `WritePage.tsx:484-495`：

```tsx
  const submit = async () => {
    ...
    try {
      const err = await onConfirm(password);
      if (err !== null) setError(err);
    } finally {
      setPassword(""); // 密碼只用於當次，送出不留存
      setPending(false);
    }
  };
```

無記住我：`grep 記住|remember frontend/src` 兩筆命中皆為**反向承諾**文案
（PrivacyPage/FaqPage：「不提供『記住我』功能…不存明文、不存雜湊」）。
後端密碼以 `SecretStr` 進 `login_sso2` 當次使用即棄（row 2 已證無任何 DB 欄位）。

**PASS.**

## Row 4 — `FEATURE_FIRST_ROUND_WRITE` 預設 false；初選送出路徑不可達

```console
$ grep -rn 'FEATURE_FIRST_ROUND_WRITE\|first_round' backend/app .env.example
backend/app/config.py:42:    feature_first_round_write: bool = False      # 預設關閉
.env.example:12:          FEATURE_FIRST_ROUND_WRITE=false                  # 文件化 false
backend/app/api/write.py:188:        first_round_write=settings.feature_first_round_write
backend/app/api/stage.py:140:  同上 (GET /api/stage 與 preview 共用同一 policy)
backend/app/write/payload.py:26: "(FEATURE_FIRST_ROUND_WRITE) - it stays out of reach here"
```

Stage 閘門 — `backend/app/stage/detect.py:209-221`：

```python
def is_writable(detection, *, need_confirmation, first_round_write) -> bool:
    if need_confirmation: return False
    if detection.stage == STAGE_ADD_DROP:   return True
    if detection.stage == STAGE_FIRST_ROUND: return first_round_write   # flag=false → False
    return False                                                        # closed/unknown → False
```

API 路徑：`POST /api/write/preview`（write.py:174-201）每次都**重新** probe Studfun，
`is_writable` 為 False → 直接 `409 ERR_STAGE`，不產 confirm_token；
`POST /api/write/submit` 只吃「通過閘門 preview 所發、單次使用（GETDEL）」的
confirm_token 並重放其 server 端 canonical_ops —— 客戶端無從繞過 flag 自造初選送單。
路由層 grep `first|quota_first|FIRST_ROUND` 無任何獨立端點。
前端（WritePage.tsx:170-173,1114,1121）：stage=初選 且不可寫時顯示
「初選志願代送尚未開放，請改用學校系統登記志願」，預檢/送出按鈕 `disabled={!writableNow}`。

**PASS.**

## Row 5 — 無代搶 / 無背景自動送單

```console
$ grep -rinE 'apscheduler|celery|schedule\.every|crontab|setInterval|backend/app backend/pyproject.toml
(零命中, EXIT=1 — setInterval/setTimeout 前端計時不含送單，見 row 8)
```

唯一背景行程 `backend/app/worker.py`（docstring:118 行）＝兩個 loop：
1. 目錄爬蟲 cron loop —— 對學校僅**唯讀 GET**（todo 6）；
2. `writeq:jobs` FIFO 的 BRPOP 單一消費者（每生序列、全域 ≤2 併發）。

而 `writeq:jobs` 全 repo 唯一生產者＝`backend/app/api/write_submit.py:144 enqueue_ticket`，
其前置＝使用者 preview → 二次確認 modal → 重打密碼當次 SSO2 重驗證。
無任何 scheduler 會在無使用者確認下 enqueue 寫入。

**PASS.**

## Row 6 — 無 auto-update / 無對外 telemetry

```console
$ grep -rnE 'fetch\(|axios|XMLHttpRequest|new WebSocket|sendBeacon' frontend/src
frontend/src/lib/api.ts:156:    fetch(path, ...)              # path = 同源相對 /api/*
frontend/src/lib/export.ts:144: fetch(`/api/plans/${planId}/export.ics`, ...)

$ grep -rinE 'auto.?update|updater|update.?check|electron' frontend/src package.json index.html backend/app
(零命中, EXIT=1)
```

前端 runtime 對外請求僅同源 `/api/*`；唯一第三方傳輸＝index.html 的 Google Fonts 靜態 link
（同 Row 1 DOCUMENTED-EXCEPTION，`qa/ui-redo-review.md` 在案）。無版本回報、無更新檢查。

**PASS.**

## Row 7 — 無碼行為斷言

**(a) 01/03（唯一碼/無此課）零臆造**：

```console
$ sed -n '60,66p;231,246p' backend/app/catalog/parse.py
#: docs/verified-facts.md "dplycourse rows and the 8-char course code":
#: NEVER appears -> None, courses.code stays NULL and the fallback identity …
def _parse_code(texts): """8-char school course code, only from the discovered column position."""
```

- 爬蟲端：課號**僅**從 dplycourse 已發現欄位抽取，不存在 → `None` 入庫（不合成）。
- 查詢端：`CourseOut.code: str | null` 原樣 pass-through（api.ts 介面；query 無加工）。
- 寫入端：`write/catalog.py resolve_course` 只以 uuid/課號查 DB；查無或 `code` 為 NULL →
  `COURSE_NOT_FOUND`（`code=None`）→ preview `VERDICT_NO_CODE = "無課號"`（preview.py:34）
  列為不可送原因，課仍可排課表（計畫缺碼行為規格）。
- 測試在案：`test_write_resolve_db.py:102-107`（null-code row resolves with code None、
  保持不可送）；`test_ics_export.py:235-239`（code=None 兩課 UID 以
  `dept|name_zh|teacher|room|class_time` 退化身份分流）；`ics.py:99-102` 實裝同規格。
- 全 repo 無「由課名/教師/時段合成 8 碼課號」的程式碼路徑。

**(b) 04/05/06-assist（螢幕 OCR / 自動點課等）缺席**：

```console
$ grep -rinE '\bOCR\b|螢幕|屏幕|screen.?capture|自動點|auto.?click|robotjs|puppeteer|playwright' frontend/src
(零命中, EXIT=1)
```

（後端 `ddddocr` solver 為計畫核准之**目錄爬蟲驗證碼**求解，非 UI 輔助點課工具。）

**(c) 無「保證加選成功」字樣**：

```console
$ grep -rn '保證\|自動搶\|代搶' frontend/src docs
TermsPage.tsx:9:  「…本站不保證與學校系統持續相容。」             ← 否定/免責
TermsPage.tsx:19: 「本站不提供自動搶課；…業務失敗…不自動重試，該課即為終態。」 ← 否定
```

**PASS (a/b/c)。**

## Row 8 — 視窗凍結：無排程寫入；寫入入口 stage 硬閘

- 無 celery/apscheduler/cron 寫學校（Row 5 證據）；背景寫入僅來自使用者確認鏈。
- 寫入 intake 由**每次即時**的 Studfun 探測硬閘（write.py:174-201 註解
  "preview never rides a cached stage"）：closed / unknown / need_confirmation / flag-off 初選
  → `409 ERR_STAGE`；submit 無 confirm_token → 400；token 重放 → 409。
- 前端凍結面：WritePage.tsx:907-908 「Closed stages flip automatically: re-probe every 60s
  while not writable」，943/1114/1121 `writableNow` 關閉時預檢與送出按鈕 `disabled`。
- F1 已同點驗證此閘門（`qa/F1-compliance.md`）。

**PASS.**

## Row 9 — 危險按鈕現實性

- **初選寫入 UI**：Row 4 — UI 顯示「初選志願代送尚未開放」並 disable；API 409 硬擋；flag 文件化 false。
- **無真退毒按鈕**：退選一律經 composer → preview → ConfirmModal，且必須輸入課號吻合
  （writeOps.ts `password_required|drop_code_mismatch`；WritePage.tsx:479-482 僅 preview ops
  內的 drop 列才可勾）。
- **live 寫入唯一紀錄**：`qa/15-live.log`（2026-08-28 10:32 CST）— 探針式：
  暫種本地 QA 目錄列 **ZZ999999**（學校不存在的課號，run 後 finally 刪除），
  實送結果 `outcome=failed【加退選失敗課程清單】`，"ZERO modification to the user's real selections"；
  學號遮蔽 `M153****24`，密碼/cookie 值從未印出。本審查**未執行任何 live 呼叫**。

**PASS.**

## Row 10 — Repo 衛生

```console
$ grep -rin '153040024' $(git ls-files)
(零命中, EXIT2=1)

$ git log --all --oneline -S '153040024'
(零命中 — 歷史任何分支皆未提交過該憑證字串)

$ cat .gitignore
.omo/        ← 在列
.env         ← 在列（含憑證環境檔不入庫）

$ ls /tmp/*creds*
/tmp/ulw-creds.env        ← 憑證 env 位於 repo 外（/tmp），非 tracked
backend/scripts/capture/creds.py:5: "STUDENT_ID / SPASSWORD; both are held in memory only and are NEVER [stored]"
```

live 紀錄一律遮蔽（`M153****24`）、stuid_hash 截斷 12 碼呈現。

**PASS.**

## 附掃 — F4 判決點逐項

| F4 判決點 | 證據 | 結果 |
|---|---|---|
| DB 或 log 出現 password/cookie 欄位或值 | Row 2 grep 零命中；F2 (`cd09817`) 安全 grep 已清理全綠 | 無 |
| 推播（LINE/Discord/email） | `grep line.me\|discord\|smtp\|sendmail\|telegram backend/app frontend/src` → 零 (EXIT2=1) | 無 |
| GA / 第三方分析 | Row 1（fonts 例外有文件） | 無 |
| torch / PyTorch / CapsNet | `grep -i 'torch\|pytorch\|capsnet' pyproject.toml uv.lock package.json` → 零 (EXIT2=1) | 無 |
| Studcheck.asp 驗證碼登入路徑 | `grep Studcheck` 排除 sso2 後原始碼零命中（僅舊 pyc 二進位碰撞） | 無 |
| 無 flag 之初選送出 | Row 4（config/stage/W^2 三層） | 無 |
| 業務失敗自動重試 | engine.py:18,82-83,101-113 `TRANSPORT_RETRIES=2` 只捕 `SelcrsUnavailable`（傳輸錯）；業務失敗即終態；重試後 duplicate-like → `unknown-reconciled`（絕不逕標失敗）；TermsPage 對使用者明示同語義 | 無 |

## Final verdict

**F4 = APPROVE**（10/10 PASS；1 項 DOCUMENTED-EXCEPTION 非 FAIL）。
計畫 F1–F4 四道最終驗收至此全數完結。
