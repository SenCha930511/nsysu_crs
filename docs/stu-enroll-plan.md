# Tier-2 實作計畫：stu_enroll（網路註冊系統）

> 狀態：**M0 已完成（2026-09-04，見 docs/verified-facts.md「consolidated reading」）**。探針 `backend/scripts/probe_stu_enroll.py` 全鏈路打通，fixtures 就位。
> 本文件 = M0 定案後的施工藍圖：讀完它即可零訪談施工 M1–M4。

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

## 2. 已驗證事實（CONFIRMED，M0 定案版——**第二層其實是四個子系統**）

| # | 事實 | 證據 |
|---|---|---|
| F1 | 舊生密碼**官方明文等同選課密碼**，且每個子系統自己的登入頁都這樣說 | stu_enroll / sco 登入頁文字 |
| F2 | **登入是 3 跳 relay**：`stu_enroll_loginchk.asp` → 自動表單(ID/passwd/cmd/action) → `regweb wregloginchk.asp` → 自動表單(ID/passwd) → `wregloginchk2.asp` → 302 `WRegMain3.asp?act=11`（註冊清單主頁，316 anchors） | `stuenroll_hop{1,2}_live_1151`、`stuenroll_regweb_main_live_1151` |
| F3 | **學校的 handoff 頁把密碼明文回顯在 hidden 欄位**——任何抓回來的頁面都可能含密碼；所有 artifact 必須同時遮學號＋密碼 | 各 hop fixture（已遮罩 `********`）；verified-facts 同條 |
| F4 | Handoff 結構特徵：**小頁面（<2KB）＋自動 `<formname>.submit()` script＋全 hidden 表單**（ID/passwd、SID/PASSWD/ValidCode、ssn1/idno 三種實測變體）；302 與 handoff **交錯**出現，跟隨器要交替處理 | consolidated 段；探針 `_follow_handoffs` 通過全鏈路 |
| F5 | Cookie 血緣：httpx `build_client(cookies=jar)` **複製**傳入 jar——Set-Cookie 只落在 `client.cookies`，每次呼叫後必須重讀覆寫，否則全部請求都匿名（M0 首輪實證 bug） | run-1 失敗紀錄 vs run-2 成功；`qa/stuenroll-m0-probe.log` |
| F6 | captcha：`/stu_enroll/validcode.asp`、`/scoreqry/validcode.asp` 與 catalog 同型（BMP 124×24 8982B）；ddddocr 單次接受率實測 **33–100%**；答錯回 200「驗證碼錯誤。/ Incorrect verified code!!」(129B) → **乾淨 4 位數閘＋5 次嘗試預算**讓登入每輪完成 | 各輪 journal；fixture `stuenroll_validcode_live_1151.bmp` |
| F7 | **成績在 sco（`selcrs.nsysu.edu.tw/scoreqry/`）**：獨立互動登入（SID/PASSWD/ValidCode＋自家 captcha）→ 自動表單 → `sco_query.asp` 302 → frameset；menu frame 有 **歷年成績查詢（action=811&KIND=3）、學期成績（700&KIND=2）、預警（817&KIND=5）** | `stuenroll_grades_frame_0_live_1151.html` |
| F8 | **繳費在 tfstu**：`act=71&out=` relay → WregRedirect → 自動表單（relay 自己轉交憑證，**零互動登入**）→ `tfstu_login_chk.asp` 302 → `tfstudata.asp?act=11`（頁面含 金金額/狀態 欄位＋`tfstu_receipt_crd_us.asp` 收據連結） | `stuenroll_payment_live_1151.html` |
| F9 | **資料確認在 verify**：relay → 自動表單(ssn1=idno & idno) → `verify_stu.asp`（80KB 確認表單，VACTION=1 是**寫操作**——不碰） | `stuenroll_verify_live_1151.html` |
| F10 | **在學證明電子版：唯讀不可達**——資料確認「已完成」後，regweb 清單與 verify 頁都沒有任何證明書連結；產生很可能掛在確認表單送出（寫）或只在剛完成時出現。早期幾輪以為抓到的「cert」其實是**新生 newstu 頁的關鍵字誤路由**，已更正 | consolidated 段 |
| F11 | TLS/編碼與 selcrs 同棧；各主機各自發 ASPSESSIONID* —— jar 是一袋多主機 | jar cookie-names 逐跳增長的 wire 紀錄 |

## 3. 未定案（UNVERIFIED）

| # | 項目 | 目前評估 |
|---|---|---|
| U1 | 各子系統 session TTL（sliding/hard 界線） | t+0 全活；界線未探——先沿用 selcrs 的 1800/7200 設定，M2 觀察再調 |
| U2 | 在學證明產生流程 | 唯讀不可達（F10）→ **本層改為導引卡**：深連結 verify/regweb + 說明，不做代理下載 |

---

## 4. M0：受監督探針 ✅ 已完成 2026-09-04（`backend/scripts/probe_stu_enroll.py`）

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
  chain.py      ── handoff+redirect 交錯 walker（提取自探針 _follow_handoffs，
                   全鏈路已實證；下面三個登入流共用）
  endpoints.py  ── login_stu_enroll_chain（→regweb jar）/ login_sco（互動式 captcha）
                   relay_tfstu / relay_verify（regweb jar 驅動的 act=71 轉發）
                   get_grades_history（sco action=811）/ get_grades_semester（700）
                   get_payment_status（tfstudata）
  classify.py   ── 依 M0 fixture 的 tri-state（含 captcha_fail marker「驗證證碼錯誤。/
                   Incorrect verified code!!」；注意 handoff 頁自帶 ValidCode 欄位，
                   歸類要用結構特徵，不能用 ValidCode 字樣）
  parse.py      ── sco 成績表 / tfstudata 金額・狀態 / regweb 清單（M0 fixture 驅動）
api:            ── app/api/stu_enroll.py（M2）
```

探針腳本的 `_follow_handoffs / _interactive_login / _fetch_captcha+_solve` 即 adapter 雛形，M1 直接提取；**在學證明不在 adapter 範圍**（唯讀不可達，見 U2→導引卡）。

### 5.2 登入與 session 策略（**關鍵決策：方案 A（fail-soft 登入時一併發放）**）

M0 後的實際 jar 地圖：**regweb jar**（經 stu_enroll 3 跳鏈免費拿到，tfstu/verify relay 都靠它）＋ **sco jar**（獨立互動登入＋自家 captcha）。

| 方案 | 內容 | 優 | 劣 |
|---|---|---|---|
| **A（推薦）** | 站內登入 SUCCESS 後，同一次密碼轉手跑 stu_enroll 鏈（captcha×1）＋ sco 登入（captcha×1），兩家族 jar 一次發放 | 使用者無感；之後全部讀取不再問密碼 | 登入延遲 +2 captcha（OCR~50%/次，重試到成功約 2–6s）；任一失敗必須 fail-soft |
| C | 首次使用每個功能時再輸密碼即場發對應 jar（比照送單二次確認） | 登入零耦合、不放大登入失敗面 | 讀取也問密碼，體驗差；且 TTL 不明（U1）下重問頻率不可控 |

**採 A，fail-soft**：子系統登入失敗**不得**阻斷站內登入；各功能卡獨立可用性旗標（`regweb_available`、`sco_available`）。登入 pipeline 在 SUCCESS 後追加子步驟，逾時上限建議 ~8s，超出即標不可用。

### 5.3 Redis 儲存（鏡像 selcrs jar 模式，兩家族）

- `regweb:{session_id}` / `regweb_hard:{session_id}` — regweb 家族 jar（涵蓋 tfstu/verify relay）
- `stusco:{session_id}` / `stusco_hard:{session_id}` — sco 家族 jar（成績）
- TTL 先沿用 `SELCRS_SESSION_TTL_SLIDING/HARD`（U1 界線不明）；logout 一併刪除（`delete_site_session` 加四把 key）
- 永不落 Postgres、永不入 log、body 永不入 access log（既有 RequestLog 只記 path+status，自然滿足）

### 5.4 Breaker

與 selcrs **共用 host 級** `breaker:school` streak：同一主機、同一脆弱前端的合理語義（任何一邊連續 unknown→全校唯讀）。若 M1 實測發現兩子系統故障域明顯分離，再拆 key——先在 architecture.md 註記此決策。

### 5.5 API（皆 session-gated；讀取不需 CSRF）

| 端點 | 內容 | 快取 |
|---|---|---|
| `GET /api/me/grades` | sco 正規化成績列（歷年 action=811 優先；GPA 由前端算，server 保持薄） | Redis session-scoped 快照（比照 selections，7d TTL）＋ `POST /api/me/grades/sync` 手動刷新 |
| `GET /api/me/payment-status` | tfstudata 金額・狀態區塊 | 短 TTL（例如 1h；或直接每次 live） |
| ~~在學證明端點~~ | **改為純前端導引卡**（F10：唯讀不可達）：深連結 regweb 主頁＋說明，不設後端端點 | — |

錯誤語義沿用既有：`SELCRS_EXPIRED`-對應的各家族 401（前端全域 soft-logout seam 已存在；detail 用 `REGWEB_EXPIRED` / `SCO_EXPIRED` 讓前端分卡提示）；學校端異常 503。

### 5.6 在學證明（改為導引，無隱私面）

唯讀探查證明：完成資料確認後校內沒有任何純 GET 的證明書入口；產生流程掛在確認表單送出（寫）上——不做代理、不做下載，就不存在 PDF 隱私問題。若日後政策改變出現唯讀入口，再按「`no-store`＋`Content-Disposition: attachment`＋不快取不落盤」規格加回端點。導引卡文案需要說明官方路徑（網路註冊系統 → 個人基本資料確認 → 產生電子版）。

### 5.7 前端

- 新路由 `/me`（RequireAuth，從第一天就進受保護群）：三張卡 —— 成績（表格（表格＋學期/累計 GPA）、繳費狀態、在學證明**導引卡**（官方路徑說明＋深連結）
- `lib/stuEnroll.ts` 純函數層（GPA 計算、列分組）＋ vitest；i18n 比照既有 `tx()` 模式
- session 狀態延伸：`regweb_available`、`sco_available` 兩個獨立旗標從登入回應帶出（A 方案的 fail-soft 對應 UI）

---

## 6. 里程碑（每個都要可驗收）

| 里程碑 | 內容 | 驗收 |
|---|---|---|
| **M0** ✅ 2026-09-04 | 受監督探針（本計畫 §4） | 全鏈路打通（regweb/sco/tfstu/verify）；verified-facts.md consolidated 段收錄定案；fixtures 齊全 |
| **M1** | `app/stuenroll/` adapter＋分類器＋解析器 | 依 M0 fixture 的單元測試全綠；不查 fixture 不寫 parser |
| **M2** | 登入 pipeline 兩家族 jar＋Redis store＋`/api/me/*` 端點＋`FEATURE_STU_ENROLL` flag（預設 off） | API 合約測試（比照 test_schedule_api／test_breaker_sitewide 模式）；全套 pytest 綠 |
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
