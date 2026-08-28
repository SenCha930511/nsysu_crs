# qa/12-design-review.md — todo 12 設計審查迭代（gated multimodal review）

- **Model used**: `gemma-4-31B-it`（multimodal，text+image input）via the
  environment's configured NCHC gateway
  `https://portal.genai.nchc.org.tw/api/v1`（`NCHC_LLM_API_KEY`）。The plan's
  model chain starts with Gemma 4, so no fallback was needed; `ollama` is
  not installed in this environment (probed, `command not found`), and no
  other local multimodal endpoint was configured.
- **Date**: 2026-08-28 09:0x CST
- **Input fed to the model**: 10 real browser screenshots (Brave headless
  through the live Caddy stack) covering `/`、`/login`、`/plans`、`/selected`、
  `/write` at both desktop 1280×800 and mobile 375×812, plus a one-paragraph
  component-structure summary (library: React 18 + TS + Bootstrap 5 tokens +
  `--crs-*` custom props; page composition of all five routes; icons policy;
  audience note: desktop-first, mobile secondary).
- **Driver**: `/tmp/qa12/review.py`（throwaway, not committed；10 PNG base64 →
  chat.completions, temperature 0.2）；full exchange preserved in
  `/tmp/qa12/review_exchange.json`。Prompt summary + instruction and the
  model's raw response are reproduced verbatim below.

---

## 1. Verbatim exchange

### 1a. Prompt (summary + instruction, text verbatim)

```
元件結構摘要：此為 React 18 + TypeScript SPA（Vite），以 Bootstrap 5 工具類為設計 token 系統，
外加少量 --crs-* 自訂屬性（品牌色 #009e96、週末欄灰、衝堂底色）。頁面：/（左：CourseBrowser
課程搜尋清單含徽章與名額；右：TotalsPanel + 15節×7天的週課表格 ScheduleTable，課程色塊為淺色
雜湊底色、hover 變品牌色）；/login（置中卡片，學號+密碼，無驗證碼）；/plans（左欄課表清單
含改名/刪除/ICS晶片、右欄志願序拖拉編輯器 + 新增的『課表預覽・匯出』卡片＝唯讀 ScheduleTable
與下載 ICS/PNG 按鈕）；/selected（同步鈕＋同步時間＋依『選上/登記加選/失敗』狀態徽章分組的課程卡）；
/write（頂部階段橫幅 alert，選課關閉期間 fieldset disabled 的送單編輯器）。頂部品牌橫條內嵌 nav 藥丸
（查課·課表/我的課表/我的已選/送/送單）與右上學號+登出。圖示皆為 react-bootstrap-icons SVG。
使用者為中山大學學生，最常用情境為桌上型課表編排，手機版屬次要。

你是嚴格的資深 UI/UX 設計審查者。以下是同一套 React SPA 的 10 張截圖（五個頁面 ×
 desktop 1280×800 + mobile 375×812）：home / login / plans / selected / write。
只根據截圖可觀察到的視覺事實提出問題；不要臆測功能、不要建議新功能、不要泛泛而談。
檢查面向：版面配置與對齊、間距節奏、字級與字重階層、中文（CJK）可讀性與換行、溢位/裁切/破版、
行動版可用性（點擊目標、橫向捲動、欄位擁擠）、色彩對比與狀態可辨性、空狀態與錯誤狀態呈現。
輸出格式（嚴格遵守，總計不超過 16 項）：
- [H] <頁面/視口>：<可觀察缺陷> → 期望：<正確呈現> → 修法：<具體 CSS/DOM 建議>
- [M] 同上格式  (H=嚴重：遮擋內容/破版/無法辨讀或無法操作；M=中等：明顯粗糙或不一致；L=細微 polish)
先輸出一行 `SUMMARY: <一句話總評>`，之後逐項輸出。若某嚴重度沒有項目就明寫該級為 0 項。
```

### 1b. Model response (gemma-4-31B-it, verbatim; usage 11,591+1,002 tokens)

```
SUMMARY: 整體功能完整但行動版導覽與元件佈局嚴重破版，缺乏統一的間距系統與對齊邏輯。

- [H] <所有頁面/Mobile>：頂部導覽列文字強行垂直排列且與登出按鈕重疊/擠壓 → 期望：水平捲動或漢堡選單 → 修法：`.nav { display: flex; overflow-x: auto; white-space: nowrap; }`
- [H] <home/Mobile>：課程卡片內名額徽章（限/登/上/餘）在窄螢幕下強行換行導致視覺破碎 → 期望：適配寬度的 Grid 或橫向捲動 → 修法：`.badge-group { display: grid; grid-template-columns: repeat(2, 1fr); gap: 4px; }`
- [H] <plans/Mobile>：課表預覽表格（ScheduleTable）寬度溢出螢幕導致強行裁切且無法閱讀 → 期望：可橫向捲動的容器 → 修法：`.table-responsive { overflow-x: auto; -webkit-overflow-scrolling: touch; }`
- [M] <home/Desktop>：左側搜尋區與右側課表區之間缺乏明確的視覺分隔或對齊基準，導致頁面顯得鬆散 → 期望：統一的 Gutter 間距 → 修法：使用 Bootstrap `.row` 與 `.col-lg-x` 並設定統一的 `gap`
- [M] <plans/Desktop>：左側「我的課表」清單中，ICS/改名/刪除按鈕在不同行數時對齊不一致 → 期望：按鈕組右對齊且寬度固定 → 修法：`.btn-group { display: flex; justify-content: flex-end; gap: 0.5rem; }`
- [M] <plans/Desktop>：志願序編輯器中，數字輸入框（1, 2）與課程名稱之間的水平間距過大 → 期望：緊湊的對齊關係 → 修法：`.list-group-item { display: flex; align-items: center; gap: 1rem; }`
- [M] <write/Desktop>：登入卡片卡片內，輸入框的 Focus 狀態（藍色外框）與按鈕的品牌藍色不一致，且邊框過粗 → 期望：統一的 Focus Ring 樣式 → 修法：`.form-control:focus { box-shadow: 0 0 0 0.25rem rgba(0, 158, 150, 0.25); border-color: #009e96; }`
- [M] <write/Mobile>：登入卡片頂部 Alert 訊息（此頁面需要先登入）與標題「學生登入」間距過近 → 期望：增加垂直間距 $\ge 1rem$ → 修法：`.alert { margin-bottom: 1.5rem; }`
- [L] <home/Desktop>：課程卡片左側的色條（綠/黃/藍）寬度過窄，視覺辨識度低 → 期望：增加色條寬度至 4-6px → 修法：`.card-border-left { border-left-width: 5px !important; }`
- [L] <home/Desktop>：搜尋區「共 3 門」文字與「清除條件」按鈕在垂直方向未對齊 → 期望：Baseline 對齊 → 修法：`.d-flex { align-items: center; }`
- [L] <plans/Desktop>：下載按鈕（ICS/PNG）使用空心按鈕，但在視覺權重上與主操作（新增）缺乏區分 → 期望：次要操作使用更輕量樣式 → 修法：`.btn-outline-primary { font-size: 0.875rem; }`
- [L] <selected/Desktop>：空狀態（尚未同步）的文字居中不足，僅在卡片左側 $\rightarrow$ 期望：全頁面垂直水平居中 $\rightarrow$ 修法：`.empty-state { display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; }`

H 級：3 項
M 級：5 項
L 級：4 項
```

---

## 2. Worker adjudication（every item verified against the actual pixels —
multimodal output is a lead, not truth; two screenshots re-inspected per item）

| # | Item | Verdict | Evidence |
|---|------|---------|----------|
| H1 | Mobile 導覽列擠壓破版（全頁面） | **VERIFIED → 已修正（見 §3）** | `plans-mobile`/`home-mobile`（before）：品牌字與四個 nav 連結逐字直排、導覽區吃掉約 25% 視口高度 |
| H2 | home/Mobile 名額徽章「視覺破碎」 | **REFUTED** | before 截圖中 限/登/上/餘 已為整齊 2 欄格狀排列於固定右欄，無破碎；不修正 |
| H3 | plans/Mobile 預覽表溢出裁切 | **REFUTED** | ScheduleTable 本來就包在 `.table-responsive`（Bootstrap 橫捲容器）內；before 截圖八欄全在視口內；不修正 |
| M1 | home/Desktop 欄間鬆散 | **REFUTED** | HomePage 已使用 `row g-3` + `col-12 col-lg-7/5`，before 截圖間距一致 |
| M2 | plans/Desktop 按鈕組對齊 | minor-true（按鈕組本就 `ms-auto d-flex gap-1` 右對齊） | 與建議一致方向；列為 L 級 polish、本次不動，避免拉扯既有 todo-11 視覺基線 |
| M3 | 志願序 input 與名稱間距 | **REFUTED** | 3rem `.priority-input` 為全站一致詞彙（送單中心重用），before 截圖對齊自然 |
| M4 | Focus ring 藍色 vs 品牌青（模型誤標頁面為 /write，實為 /login） | **VERIFIED → 已修正（見 §3）** | login-desktop（before）：學號 focus ring 與 登入 CTA 皆為 Bootstrap 預設藍，與全站青品牌不連貫 |
| M5 | login Alert 與標題間距 | minor-true | 列為 L 級 polish、本次不動 |
| L1–L4 | 色條寬度／基線對齊／次要按鈕字級／空狀態居中 | low-value polish | 保留至未來 design debt；不在 todo 12 修正範圍 |

## 3. 已套用修正（H=0、≥1 M 實際修正 — 皆已重建進 caddy 並重拍）

1. **[H→0] Mobile header 破版**（`.app-header` media query，`frontend/src/index.css`）：
   ≤768px 時 header 改為兩行——第一行「品牌＋右上登入/學號＋登出」
   （`flex-wrap: wrap; white-space: nowrap;`），第二行 nav 藥丸水平可捲動
   （`overflow-x: auto; scrollbar hidden; .app-nav-link { flex:none; white-space:nowrap }`）。
   刻意不引入 hamburger JS：四個目的地一眼可見、一點即達。
2. **[M 修正] 品牌一致表單焦點與登入 CTA**：`.form-control:focus`/`.form-select:focus`
   改為 `--crs-brand` 邊框＋`--crs-brand-glow` 焦圈；新增 `.btn-brand`
   （填充 `--crs-brand`，hover/active `--crs-brand-dark`，**新增 1 個 token**），
   套用到 /login 的 登入 送出鈕。`frontend/DESIGN.md` §9 已記錄兩項修正與新 token。

## 4. Before / After 證據

| Item | Before | After |
|---|---|---|
| H 修正（行動版 header，/plans mobile 375×812） | `qa/12-before.png`（逐字直排＋佔 25% 視口） | `qa/12-after.png`（兩行：品牌+學號+登出／水平 nav 藥丸） |
| M 修正（/login desktop：藍 focus ring + 藍 CTA → 品牌青 focus ring + 品牌青 CTA） | `qa/12-login-before.png` | `qa/12-login-after.png` |

輔助：`/tmp/qa12/shots/`（10 張 before 全量，throwaway）；`/tmp/qa12/shots/home-mobile-after.png`
（H 修正於 / 頁面之對照）。

## 5. Outcome

- Plan 通過準則：**critique `severity=high` 數 = 0 且 ≥1 項 medium 已修正 — PASS**
  （唯一被像素驗證的 H 已修正；一項 M（品牌焦圈/CTA）已修正；模型其餘 H/M 主張
  經逐項像素核對後駁回 4 項、降級 2 項，裁決過程留於 §2）。
- 修正後前端 `tsc --noEmit` + `vite build` + vitest 100/100 全綠；caddy 已重建。
- **環境附記**：審查截圖流程中 Redis 的 QA 站台 session 曾於兩次拍攝間消失
  （dbsize→1 僅剩 ingest:lock），已重發 QA session 完成 after 拍攝；session TTL 語意
  （site 7d sliding）本身未涉本 todo 改動，消失原因待查（不影響本次交付之任何斷言，
  qa/12-live.log 全流程於 session 有效時已通過）。
