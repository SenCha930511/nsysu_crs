/** 隱私權政策 (todo 17): credentials policy, PII minimization, audit lifecycle. */

import LegalPage, { type LegalSection } from "../components/LegalPage";
import { useI18n } from "../lib/i18n";

const SECTIONS_ZH: LegalSection[] = [
  {
    heading: "本服務定位（非官方聲明）",
    paragraphs: [
      "本站為學生自行建置與維運之第三方課程查詢與選課輔助工具，與國立中山大學之間無任何隸屬、委任、合作或背書關係。學校之正式選課紀錄與系統狀態，一律以中山大學選課系統（selcrs.nsysu.edu.tw）為準。",
    ],
  },
  {
    heading: "我們不儲存任何形態的學校密碼",
    paragraphs: [
      "本站的核心承諾：你的學校選課密碼「不落地」。我們不儲存明文、不儲存任何形式的雜湊值，也不提供「記住我」功能。密碼僅在登入或送單二次確認的當下，於伺服器記憶體中用於向學校系統驗證身分，使用後立即丟棄，不寫入任何資料庫、檔案或日誌。",
      "登入成功後，學校系統核發的 selcrs 工作階段 cookie 在本站「視同憑證」管理：它僅保存於 Redis（記憶體層）並設定短效 TTL（滑動 30 分鐘、上限 2 小時），永不寫入 Postgres，也永不寫入任何日誌。一旦 Redis 異常，登入與寫入功能會直接失敗並明示，查課等讀取功能不受影響。",
    ],
  },
  {
    heading: "個資最小化原則",
    paragraphs: [
      "本站只保存提供服務所必要的最少資料，且多數與個人直接相關的資料都設定自動到期：",
    ],
    list: [
      "學號：作為登入識別與課表組合之歸屬。",
      "課表組合與志願序：你主動建立的內容，可隨時自行刪除。",
      "「我的已選」同步結果：僅保存於你本次工作階段的範圍內（登出或工作階段到期即刪除），不持久保存於資料庫。",
      "課程目錄：來自學校公開查詢頁面，不含任何個人資料。",
      "本站不收集姓名、電子郵件、電話、成績或任何校務資料；不使用 Google Analytics 或任何第三方分析／追蹤工具；不建立本站 email 註冊體系。",
    ],
  },
  {
    heading: "稽核紀錄與去識別化生命週期",
    paragraphs: [
      "代送（寫入）操作會留下稽核紀錄，以供異常對帳與責任釐清。稽核中的學號一律以「加鹽雜湊」關聯，不儲存明文學號；學校回應中的學號亦於入庫前遮罩。其生命週期為：",
    ],
    list: [
      "熱層保存 90 天：可對帳、可查詢。",
      "去識別化歸檔：90 天屆滿後以去識別化形式壓縮（gz）歸檔，再保存 1 年。",
      "刪除：歸檔屆滿 1 年後永久刪除。",
    ],
  },
  {
    heading: "資料來源",
    paragraphs: [
      "課程資料全部由本站爬蟲自國立中山大學選課系統之公開課程查詢頁面（無需登入即可瀏覽之頁面）取得：平日每小時更新、選課窗口期間每 10 分鐘更新。爬取失敗時，本站以最後一次成功之快照繼續提供瀏覽，並於頁首公告該快照的更新時間。",
    ],
  },
  {
    heading: "聯絡管道",
    paragraphs: [
      "GitHub 倉庫提 issue：https://github.com/SenCha930511/nsysu_crs；或寄信至 sencha930511@gmail.com。",
    ],
  },
  {
    heading: "政策更新",
    paragraphs: [
      "本政策如有重大變更，將於本站明顯位置公告後生效。",
    ],
  },
];

const SECTIONS_EN: LegalSection[] = [
  {
    heading: "Service status (unofficial notice)",
    paragraphs: [
      "This site is a student-built, third-party course-browsing and selection helper. It has no affiliation, mandate, partnership, or endorsement from National Sun Yat-sen University. The school's formal selection records and system state are authoritative only at the NSYSU course-selection system (selcrs.nsysu.edu.tw).",
    ],
  },
  {
    heading: "We never store your school password in any form",
    paragraphs: [
      "The core promise: your course-selection password never lands on disk. We store no plaintext, no hash of any kind, and there is no “remember me”. The password lives only in server memory during sign-in and the second-confirm of submissions, is used to authenticate against the school system, and is discarded immediately — never written to any database, file, or log.",
      "After sign-in, the selcrs session cookie issued by the school is treated as a credential: it stays only in Redis (memory layer) with a short TTL (sliding 30 minutes, hard cap 2 hours), never in Postgres, never in any log. If Redis fails, sign-in and submit features fail loudly while read-only browsing keeps working.",
    ],
  },
  {
    heading: "Data minimization",
    paragraphs: [
      "We keep only the minimum data required to serve you, and most person-linked data expires automatically:",
    ],
    list: [
      "Student ID: identifies sign-in and owns your plans.",
      "Plans and priority orders: created by you, deletable by you anytime.",
      "Synced “my selections”: scoped to your current session only (deleted on sign-out or expiry) — never persisted long-term.",
      "Course catalog: scraped from the school's public query pages and contains no personal data.",
      "We do NOT collect names, emails, phone numbers, grades, or any school-records data; we use no Google Analytics or third-party tracking; there is no email registration system on this site.",
    ],
  },
  {
    heading: "Audit records and de-identification lifecycle",
    paragraphs: [
      "Submit (write) operations leave an audit trail for reconciliation and accountability. Student IDs inside audits are only linked via a salted hash — never stored in plaintext; IDs echoed back by the school are masked before they reach the database. Lifecycle:",
    ],
    list: [
      "Hot tier for 90 days: reconcilable and viewable.",
      "De-identified archive: after 90 days, compressed (gz) in de-identified form for 1 more year.",
      "Deletion: permanently removed once the archive year ends.",
    ],
  },
  {
    heading: "Data source",
    paragraphs: [
      "All course data is scraped by our crawler from the public course-query pages of the NSYSU course-selection system (pages readable without sign-in): hourly on normal days, every 10 minutes during selection windows. If scraping fails, the site keeps serving the last successful snapshot and announces its update time at the top of the page.",
    ],
  },
  {
    heading: "Contact",
    paragraphs: [
      "Open an issue on the GitHub repo: https://github.com/SenCha930511/nsysu_crs — or email sencha930511@gmail.com.",
    ],
  },
  {
    heading: "Policy updates",
    paragraphs: [
      "Material changes to this policy take effect after being announced at a visible spot on this site.",
    ],
  },
];

function PrivacyPage() {
  const { lang, tx } = useI18n();
  return (
    <LegalPage
      title={tx("隱私權政策", "Privacy Policy")}
      intro={tx(
        "本頁說明本站如何（不）處理你的憑證與個人資料：密碼零落盤、cookie 僅記憶體短效保存、個資最小化、稽核去識別化生命週期。",
        "How this site does (not) handle your credentials and personal data: passwords never persisted, session cookies kept memory-only and short-lived, data minimization, de-identified audit lifecycle.",
      )}
      sections={lang === "en" ? SECTIONS_EN : SECTIONS_ZH}
    />
  );
}

export default PrivacyPage;
