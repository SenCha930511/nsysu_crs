# Tier-2 實作計畫：stu_enroll（網路註冊系統）

> 狀態：M0 探針就緒（`backend/scripts/probe_stu_enroll.py`），等第一次受監督執行。
> 本文件是第二層功能的完整藍圖：讀完它 + 一次 M0 執行紀錄，即可零訪談施工 M1–M4。

---

## 1. 目標與範圍

為已登入的學生提供 stu_enroll（`https://selcrs.nsysu.edu.tw/stu_enroll/`，網路註冊系統）的三個功能：

| 功能 | 價值 | 型態 |
|---|---|---|
| **舊生成績查詢** | 成績 + 前端自算 GPA；「這門修過沒／被當過沒」的選課輔助 | 讀取（session-gated） |
| **在學證明電子版** | 教務處公告：在網路註冊系統完成「個人基本資料確認」後產生 | 讀取／下載（PDF passthrough） |
| **繳費狀態查詢** | 註冊狀態提醒 | 讀取 |

**明確不做（本層範圍外）**：

- `naca_apply`（線上申請成績單及各類證明文件）——身分證＋生日登入、牽涉金流，只做導引（第三層）。
- `progcert` 學程證書申請——窗口期導引（第三層）。
- 任何 stu_enroll 內的**寫操作**（休學申請、資料修改、個人基本資料確認的送出）——永遠只讀，牽涉學籍狀態變更的動作一律導回學校網站。

---

## 2. 已驗證事實（CONFIRMED）

| # | 事實 | 證據 |
|---|---|---|
| F1 | 舊生登入密碼**官方明文等同選課密碼**（「舊生密碼預設值：同選課密碼」） | stu_enroll 首頁公開說明文字；fixture `stuenroll_login_live_1151.txt` |
| F2 | 開放期間 115-1 為 2026/08/01–2027/01/31（有窗口期的子系統） | 同上 |
| F3 | 登入表單：`POST stu_enroll_loginchk.asp`，欄位 `IDtmp`(學號可見) / `passwdtmp`(密碼可見) / `ID` / `passwd`（hidden，前端 JS `copyid()`/`copypw()` 純複製，**無雜湊轉換**）/ `ValidCode`(驗證碼) / `b1` | M0 匿名輪 2026-09-04：`inputs=['ID','IDtmp','ValidCode','b1','passwd','passwdtmp']`，missing=none；log `qa/stuenroll-m0-probe.log` |
| F4 | 驗證碼 `GET validcode.asp?epoch=<ms>` 回 **Image/BMP 124×24、8982 bytes**，與 catalog 的 `menu1/validcode.asp` 同型同尺寸，發放 ASPSESSION cookie；答案綁定發放 session | M0 fixture `stuenroll_validcode_live_1151.bmp`（與 verified-facts 的 validcode 條目比對一致） |
| F5 | 專案現有 ddddocr 引擎（`app/solver/ocr.py`）對真實 captcha 的 4 位數命中率 **9/10** | M0 匿名輪 `--samples 10`；log 同上 |
| F6 | 首頁側欄列出功能連結：舊生成績查詢、繳費狀態查詢、報到前資料確認等 | fixture `stuenroll_login_live_1151.html` |
| F7 | TLS/編碼與 selcrs 同棧：legacy TLS（`OP_LEGACY_SERVER_CONNECT`）、per-response charset（sys 404 頁為 big5） | 既有 `app/selcrs/http.py`、`decode.py` 直接適用，已於 M0 實跑驗證 |

## 3. 未驗證假設（UNVERIFIED — M0 受監督輪要定案）

| # | 假設 | 風險 |
|---|---|---|
| U1 | **同密碼實際可登入**（F1 是官方文件說法，未實測） | 若否 → 三功能全退回導引層 |
| U2 | 登入成功的 wire 形狀（302 到哪；200 時是否即主頁）與失敗 marker（驗證碼錯誤／密碼錯誤文字） | 分類器需要 live fixture 才能寫成分類器（比照 `sso2.py` tri-state） |
| U3 | 登陸後 menu/frames 結構，成績、繳費、證明頁的**實際路徑** | 解析器選擇器需要 fixture |
| U4 | 成績頁表格形狀（學期成績 vs 歷年；GPA 是否校方已算） | 解析器 + GPA 計算分工 |
| U5 | 在學證明產生流程：「個人基本資料確認」的完成狀態、PDF 產生是 GET 還是 POST、URL 形式、是否含敏感欄位（身分證字號） | 決定 passthrough 的可行性與隱私處理 |
| U6 | stu_enroll session TTL（sliding/hard 界線）、與 selcrs session 是否互相干擾（同 ASPSESSION 家族） | jar 生命週期設計；並存風險 |

---

## 4. M0：受監督探針（已交付，`backend/scripts/probe_stu_enroll.py`）

**絕對律**：外部請求只有登入 POST（≤3 次、僅 captcha 錯誤才重試、密碼錯誤永不重試）＋ captcha BMP＋純 GET。不做任何其他 POST、不送出任何表單。密碼僅記憶體、wire body 不落盤、fixture 學號原位遮罩、journal 只記 cookie 名。

```bash
# 匿名輪（已執行過）：驗證表單形狀 + OCR 命中率
cd backend && uv run python -m scripts.probe_stu_enroll --no-login --samples 10

# 受監督輪（需要本人執行）：在寫入任何 credential 前先建 env 檔（repo 外、600 權限）
printf 'STUDENT_ID=M1xxxxxxx\nSPASSWORD=你的選課密碼\n' > ~/stu-creds.env && chmod 600 ~/stu-creds.env
cd backend && uv run python -m scripts.probe_stu_enroll --creds-env ~/stu-creds.env

# 連證明頁一起抓（純 GET；會先問 yes）
cd backend && uv run python -m scripts.probe_stu_enroll --creds-env ~/stu-creds.env --with-cert
```

**產出（M1–M4 的原料）**：

- `backend/tests/fixtures/stuenroll_{login,validcode,loginresp_attemptN,landing,frame_N,grades,payment,cert}_live_1151.{html,txt,bmp,pdf}`
- `qa/stuenroll-m0-probe.log`（每次外呼＋唯讀理由的帳本）
- `docs/verified-facts.md` 自動追加 `## live-verified (stu_enroll 115-1 m0)` 段落（U1–U6 逐條定案為 CONFIRMED / UNVERIFIED）

**判讀**：exit 0＝登入成功且流程完整；1＝登入未達成功形狀（看 attempt fixture 與分類紀錄）；2＝creds 檔案不符規格；3＝學校端異常。

---

## 5. 架構設計

### 5.1 分層（鏡像 `app/selcrs` 的紀律）

```
app/stuenroll/
  http reuse    ── 直接沿用 app/selcrs/http.py 的 build_client/request_school
                   （legacy TLS、全行程 semaphore=2、backoff 1/2/4/8/16s）
  decode reuse  ── 沿用 app/selcrs/decode.py（per-response charset）
  ocr reuse     ── 沿用 app/solver/ocr.py
  endpoints.py  ── fetch_login_page / fetch_validcode / login_stu_enroll（tri-state）/
                   get_grades / get_payment_status / get_enrollment_cert
  classify.py   ── 依 M0 fixture 寫 SUCCESS/CREDENTIAL-FAIL/CAPTCHA-FAIL/UNKNOWN 分類器
  parse.py      ── grades 表格 / payment 區塊解析（M0 fixture 驅動，shape drift → SelcrsUnavailable）
api:            ── app/api/stu_enroll.py（M2）
```

探針腳本內的 `_fetch_captcha/_solve/_login` 即未來 adapter 的雛形，施工時直接提取。

### 5.2 登入與 session 策略（**關鍵決策：方案 A（fail-soft 雙登入）**）

| 方案 | 內容 | 優 | 劣 |
|---|---|---|---|
| **A（推薦）** | 站內登入成功後**同一次密碼轉手**多打一條 stu_enroll 登入，兩顆 jar 併存 | 使用者無感；讀取功能不需要再驗密碼 | 登入路徑多一個學校接觸點；stu_enroll 掛時要 fail-soft |
| C | 首次使用 stu_enroll 功能時要求**再輸入一次密碼**（比照送單二次確認）即場發 jar | 登入零耦合 | 每次 jar 過期都重問密碼；讀取型功能體驗差 |

**採 A，fail-soft**：stu_enroll 登入失敗（任何分類）**不得**阻斷站內登入；記 `stuenroll_available=false` 到 session 範圍，前端對應卡片顯示「暫時無法使用」。站內登入 pipeline 的第 6 步（SUCCESS 後）追加一個子步驟發 stu_enroll jar；整體登入延遲增加約一次 captcha+POST（~1–2s）。

### 5.3 Redis 儲存（鏡像 selcrs jar 模式）

- `stuenroll:{session_id}` — 序列化 jar，sliding TTL
- `stuenroll_hard:{session_id}` — `SET NX EX` hard cap
- TTL 值**暫時沿用** `SELCRS_SESSION_TTL_SLIDING/HARD`；M0 U6 定案後再評估是否獨立旋鈕
- logout 時一併刪除（`delete_site_session` 加兩把 key）
- 永不落 Postgres、永不入 log、body 永不入 access log（既有 RequestLog 只記 path+status，自然滿足）

### 5.4 Breaker

與 selcrs **共用 host 級** `breaker:school` streak：同一主機、同一脆弱前端的合理語義（任何一邊連續 unknown→全校唯讀）。若 M1 實測發現兩子系統故障域明顯分離，再拆 key——先在 architecture.md 註記此決策。

### 5.5 API（皆 session-gated；讀取不需 CSRF）

| 端點 | 內容 | 快取 |
|---|---|---|
| `GET /api/me/grades` | 正規化成績列（GPA 由前端算，server 保持薄） | Redis session-scoped 快照（比照 selections，7d TTL）＋ `POST /api/me/grades/sync` 手動刷新 |
| `GET /api/me/payment-status` | 繳費狀態區塊 | 同上（短 TTL，例如 1h；或直接每次 live） |
| `GET /api/me/enrollment-cert` | **PDF passthrough**：即時取、串流回應 | **不快取、不落盤** |

錯誤語義沿用既有：`SELCRS_EXPIRED`-對應的 stu_enroll 版本回 401（前端全域 soft-logout seam 已存在，detail 用 `STUENROLL_EXPIRED` 讓前端可區分提示）；學校端異常 503。

### 5.6 在學證明的隱私設計（最高敏感級）

- 可能含姓名／學號／身分證字號 → 回應 `Cache-Control: no-store`、`Content-Disposition: attachment`（配合現行 CSP `object-src 'none'`，不內嵌顯示）
- PDF bytes 不進任何快取／DB／日誌；masking 不適用於給使用者本人的文件（這是使用者自己的資料）
- Privacy page（`PrivacyPage.tsx`）與 `docs/architecture.md` 的機密資料政策要補一段：在學證明屬於「經手不落地」類別

### 5.7 前端

- 新路由 `/me`（RequireAuth，從第一天就進受保護群）：三張卡 —— 成績（表格＋學期/累計 GPA）、在學證明（下載按鈕＋狀態說明）、繳費狀態
- `lib/stuEnroll.ts` 純函數層（GPA 計算、列分組）＋ vitest；i18n 比照既有 `tx()` 模式
- session 狀態延伸：`stuenroll_available` 旗標從登入回應帶出（A 方案的 fail-soft 對應 UI）

---

## 6. 里程碑（每個都要可驗收）

| 里程碑 | 內容 | 驗收 |
|---|---|---|
| **M0** | 受監督探針（本計畫 §4） | U1–U6 全部(CONFIRMED/UNVERIFIED)定案入 verified-facts.md；fixtures 齊全 |
| **M1** | `app/stuenroll/` adapter＋分類器＋解析器 | 依 M0 fixture 的單元測試全綠；不查 fixture 不寫 parser |
| **M2** | 登入 pipeline 雙 jar＋Redis store＋`/api/me/*` 端點＋`FEATURE_STU_ENROLL` flag（預設 off） | API 合約測試（比照 test_schedule_api／test_breaker_sitewide 模式）；全套 pytest 綠 |
| **M3** | 前端 `/me` 三卡＋i18n＋GPA 純函數 | vitest＋tsc 綠；feature flag 控制可見性 |
| **M4** | QA 證據輪＋文件＋上線 | qa 證據腳本（比照 qa08/qa15 模式）跑綠；architecture.md、verified-facts.md、Privacy page 更新；README 功能表更新；灰度開 flag |

工期估計：M0（本人 10 分鐘）→ M1–M3（各一個工作段落）→ M4（半天含部署）。

---

## 7. 附錄：關鍵線索引

- 登入頁 `GET https://selcrs.nsysu.edu.tw/stu_enroll/`（fixture：`stuenroll_login_live_1151`）
- 送出點 `POST https://selcrs.nsysu.edu.tw/stu_enroll/stu_enroll_loginchk.asp`，body 為 big5 百分號編碼的 x-www-form-urlencoded（比照 capture kit `FORM_TEXT_ENCODING`）
- 驗證碼 `GET https://selcrs.nsysu.edu.tw/stu_enroll/validcode.asp?epoch=<ms>`（答案綁發放 session：BMP 與 POST 必須同一 jar 血緣）
- cookies：`ASPSESSIONID*`（自登入頁/驗證碼發放）＋`BIGipServerPL-Selcrs`＋`TS01*`
- 分流決策痕跡：`copyid()/copypw()` JS 證明 hidden 欄位為純複製（無 base64md5）
- 既有可重用模組：`app/selcrs/http.py`、`app/selcrs/decode.py`、`app/solver/ocr.py`、`scripts/capture/creds.py`、`scripts/capture/readonly.py`（遮罩/帳本模式）
