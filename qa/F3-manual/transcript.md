# F3 — 真實端到端手動 QA（worker 親走）— transcript

- 日期：2026-08-28（115-1 加退選一窗口 09:00–08-31 17:00 內，Asia/Taipei）
- 場域：本機 compose 全棧（caddy:80 唯一入口；app+worker 為 todo-15 碼），`http://localhost`
- 驅動：worker 親用真實 UI —— playwright-core 1.62.1（npx cache）＋ system Brave headless；驅動與種子檔皆存於 /tmp，未入庫
- 憑證：[CREDS] 由 `/tmp/ulw-creds.env`（STUDENT_ID/SPASSWORD，chmod 600，repo 外）讀入記憶體；學號全程以 `M153****24` 遮罩（截圖前做 DOM 置換＋所有 log 字串置換）；密碼只打過兩次（登入一次、送單 modal 重打一次），不落任何檔
- 鐵律遵守：全程唯一送往學校的「寫」＝**加選不存在課號 ZZ999999**（學校必拒），真實已選零變更（見 step 5 與收尾證據）

## 環境前置（窗口態與目錄）

- `/api/health` 200（postgres ok / redis ok）；`/api/catalog/meta` ok=true、row_count=2596、source=self-scrape
- `/api/ops/state` breaker.state=closed（normal mode）
- 本批 `[WINDOW]` 子步驟全部於窗口內執行，**無任何 DEFERRED-TO-1152**；初選志願 flag 未觸碰（`FEATURE_FIRST_ROUND_WRITE=false` 維持，未做任何初選送單）

## 逐步紀錄（action → observation → verdict）

| # | 步驟 | 動作 | 觀察 | 判定 |
|---|------|------|------|------|
| 1 | 登入（01-login.png） | /login 真實輸入帳密 → 送出 | SSO2 成功、落 /plans；頂欄用戶晶片在（截圖遮罩）；回首頁 `table.schedule-table` 週課表格在；搜「人工智慧導論」實載 4 列（徽章 限/登/上/額滿 真數據） | **PASS** |
| 2 | 二組課表＋志願序＋衝堂（02-plans.png） | UI 建 乙（首組自動主課表）→ 建 甲 → 星標把 甲 設主課表；甲加入 人工智慧導論(AI聯盟學，四567)、基礎程式設計（C++）（一234)、生成式AI…（二89C)3 門；統計 已選 3 門/總學分 9/總時數 9 節 | 每次加入皆有 autosave PUT；伺服器端 items=3 | **PASS** |
| 2b | 衝堂染色 | 搜「資料探勘與應用」（一234，與 C++ 撞） | 該列出現 `course-row-conflict` 染色（截圖可見紅底列）；點加入後統計晶片 衝堂 1 組/已選 4 門；移除後回到 3 門、衝堂消失 | **PASS** |
| 2c | 乙 1 門＋改名/刪除 undo | 乙加 企業倫理與公司治理；乙→改名「乙已驗」→改回「乙」（PATCH 見證）；另建「刪我」後 UI 刪除（confirm 對話框） | 乙 items=1；改名兩向皆生效；「刪我」刪除後伺服器查無 | **PASS** |
| 2d | 志願序 1–3 | /plans 對 甲 三課逐列輸入 1,2,3（blur 自動存 PUT） | 伺服器端 priorities == {AI導論:1, C++:2, 生成式AI:3} | **PASS** |
| 3 | 匯出 ICS/PNG（03-export.png） | /plans 選 甲 → 下載 ICS、下載課表 PNG | ICS `nsysu-crs-甲.ics`（1341B）；PNG `nsysu-crs-甲-20260828.png`（216329B、1798×1606，非空白）；icalendar 解析：VEVENT=3（每課一平日段）、VTIMEZONE=1、DTSTART TZID=Asia/Taipei、每事件 RRULE UNTIL=20270116T155959Z（UTC DATE-TIME）、UID 確定性尾碼 @nsysu-course-wrapper → 見 `ics-check.txt`（ICS_CHECK_EXIT=PASS） | **PASS** |
| 4 | 我的已選同步（04-selected.png） | /selected → 按「同步我的已選」（真實 slt_result 讀取） | 同步 200；上次同步 2026-08-28T11:45:52+08:00；狀態 {選上:5}；diff 新增 5｜移除 0｜未變 0（空快取首同步）；5 張真實已選卡（CSE515/520/530/531/729；研究所課碼本目錄查無→如實標示，不擋） | **PASS** |
| 5 | 送單中心（05-write.png） | psql 種本地 QA 目錄列 ZZ999999（send_probe 同款 INSERT）→ UI 建「送單QA」設主課表＋搜「QA 探針」加入 → /write | 階段閘門（真實 Studfun 探測）：`目前為選課開放期間：加退選`（alert-success，表單 ssform，偵測 11:45:56）= writable 真值 | **PASS** |
| 5b | 預檢 | 組 1 筆加選（志願 1）→ 預檢本批 | verdict data-tone=pass 通過；名額快照警示如實出現（`名額為目錄快照（更新於 2026-08-28T03:45:52Z…），實際以學校系統當下為準`） | **PASS** |
| 5c | 二次確認 → 送出 | modal 確認清單（＋加選 QA 探針… 志願 1）→ **當下重打密碼一次** → 確認送單 | submit 202 入隊；job 輪詢（UI 2s）→ 終態 已完成 | **PASS** |
| 5d | 逐課結果 | — | op +ZZ999999 **outcome=failed（業務失敗終態）**，學校原文 `【加退選失敗課程清單】`；job JSON（遮罩）存 `job-terminal.json`；稽核列與 15-live 同型 | **PASS** |
| 5e | 對帳 | reconcile 按「重新同步已選」（真實重查） | 已同步（11:46:01）新增 0｜移除 0；差異表：本批意圖 加選(志願1) × 學校最新狀態 **已選清單無此課** → 不一致（學校拒絕之正確如實呈現） | **PASS** |
| 5f | 清理 | finally psql DELETE ZZ999999；目錄 API 複查 | 查無 ZZ999999（本批全程真實已選零變更——唯一校側寫入即此筆必拒之加選） | **PASS** |
| 6 | 降級演練（06-degrade.png；degrade-proof.txt） | **採用變體：qa/15-redisdown 模式 —— `docker compose stop redis`**（未選 SELCRS 指死埠變體；此變體非破壞、可完整復原） | redis 停：`/api/health`→503（redis ConnectionError, postgres ok）；`GET /api/courses` 200、meta 200(ok,2596)、前端 200（讀取面全活）；**真實登入嘗試→503 `{"detail":"redis_unavailable"}`**（login 寫邊就地硬失敗，零學校流量）；登入頁 inline 降級警示 `學校系統異常，稍後再試／你仍可瀏覽課程目錄與本機課表`（截圖）。裸 curl（無 session）寫邊先被驗證/CSRF 邊擋（422/403 為外層閘），authenticated 寫邊 503 由既有 `qa/15-redisdown.log` 同碼矩陣在案。復原：start redis → health 200 → **全新真實登入成功**（復歸證明） | **PASS** |

## 收尾清理與康健

- 測試課表：送單QA、甲、乙 全部由 UI 刪除；`/api/plans` 查無任何 QA 遺留（running plans = 0）
- QA 目錄列 ZZ999999：已刪、API 複查無
- 真實已選佐證（sel_proof，真實重查）：{選上:5} ＝ 送單前基線，課碼集相同，ZZ999999 不在真實已選
- 堆疊康健：`/api/health` 200；`/api/catalog/meta` ok=true、row_count=2596（≈2596 達標）；compose 五服務在、redis health 回 ok
- 頂欄 degrade-banner 於 redis-down 情境**如實未出現**：該 banner 只對映「目錄快照失效（ok=false)」與「breaker 開」兩態（lib/degrade.ts），redis 斷線依設計呈現為寫邊 503＋inline 降級警示＋讀取面照常；特此註記

## 探測/降級證明行

- 線路證明（wire proof）：`qa/15-live.log` 在案（2026-08-28 10:32 CST run, SEND_EXIT=0, outcome=failed `【加退選失敗課程清單】`）；本批 F3 再以**真實 UI 全鏈**重證一次（本檔 step 5）
- 降級證明：`qa/F3-manual/degrade-proof.txt`（job 終態遮罩 JSON：`qa/F3-manual/job-terminal.json`）

## 檔案清單

- 01-login.png（登入後首頁：週課表格＋真目錄列）
- 02-plans.png（衝堂染色列＋統計＋左側 3 門課表在格）
- 03-export.png（甲/乙 列＋主課表徽＋志願 1–3＋匯出卡）
- 04-selected.png（選上 5 門＋同步時間＋diff）
- 05-write.png（加退選閘門＋已完成 job＋ZZ999999 failed＋對帳不一致列）
- 06-degrade.png（redis 停時登入頁 inline 降級警示）
- ics-check.txt / job-terminal.json / degrade-proof.txt / 本檔

## 結論

**F3 = PASS（全步驟窗口內執行，無 DEFERRED-TO-1152）。** 真實已選全程零變更；初選 flag 未觸碰；唯一校側寫入為必拒之 ZZ999999 加選且如實呈現。
