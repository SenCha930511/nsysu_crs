/** 常見問題 (todo 17): Q&A carrying the plan-mandated advisories. */

import LegalPage, { type LegalSection } from "../components/LegalPage";
import { useI18n } from "../lib/i18n";

const SECTIONS_ZH: LegalSection[] = [
  {
    heading: "Q1：你們會儲存我的選課密碼嗎？",
    paragraphs: [
      "不會。任何形態都不儲存：不存明文、不存雜湊、沒有「記住我」。密碼只在登入與送單確認的當下於記憶體中使用後丟棄。學校核發的 selcrs cookie 視同憑證：只放記憶體層 Redis、短效 TTL（滑動 30 分鐘、上限 2 小時），永不寫進資料庫或日誌。細節見「隱私權政策」。",
    ],
  },
  {
    heading: "Q2：聽說預設密碼是身分證後六碼，我需要做什麼嗎？",
    paragraphs: [
      "需要。學校系統的初始密碼就是你的身分證字號後六碼；若你從未更換，等於任何知道你學號與身分證後六碼的人都能以你的名義登入。請立即至學校系統更換為高強度密碼。本站無法代你更換，也不接受密碼託管。",
    ],
  },
  {
    heading: "Q3：為什麼我的帳號被鎖定 15 分鐘？",
    paragraphs: [
      "同一學號在 15 分鐘內累積 5 次被學校判定密碼錯誤，即觸發固定 15 分鐘鎖定；鎖定期間本站一律就地拒絕、不再向學校發送嘗試，且「成功登入不會洗白失敗紀錄」。此機制「僅保護本站」免於暴力嘗試——學校端另有其自有的異常偵測與鎖定規則，兩者無關；若你在學校端被鎖定，請洽學校相關單位。",
    ],
  },
  {
    heading: "Q4：有人一直故意觸發我的鎖定，害我不能用，怎麼辦？",
    paragraphs: [
      "這是已知的濫用型態（「目標帳號連續觸發鎖定」）：攻擊者約每 15 分鐘送 5 次錯誤密碼嘗試，就能讓特定學號近乎常鎖。本站對鎖定事件設有不明文化的計數監測與管理員回應 SOP：異常增加時會公告並採取應變。也請你更換高強度密碼，並留意學校端通知。",
    ],
  },
  {
    heading: "Q5：為什麼有時整站變成唯讀？",
    paragraphs: [
      "當學校系統連線失敗或回應異常連續達門檻，本站熔斷器會開啟，全站進入唯讀安全模式：查課、排課表維持可用，登入與送單暫停，頁首會有明顯提示。學校恢復並通過探活後自動解除，不需你操作。",
    ],
  },
  {
    heading: "Q6：課程資料從哪裡來？多久更新一次？",
    paragraphs: [
      "全部來自中山大學選課系統的公開課程查詢頁面（免登入頁面）：平日每小時更新、選課窗口期間每 10 分鐘更新。若同步失敗，本站以最後成功快照續供，並在頁首公告該快照的更新時間。",
    ],
  },
  {
    heading: "Q7：這是學校的官方服務嗎？",
    paragraphs: [
      "不是。本站是學生自建的第三方輔助工具，未經校方委任或背書；正式資訊與選課紀錄以中山大學選課系統為準。",
    ],
  },
  {
    heading: "Q8：我要怎麼聯絡你們或回報問題？",
    paragraphs: [
      "兩個管道：GitHub 倉庫提 issue（https://github.com/SenCha930511/nsysu_crs），或寄信至 sencha930511@gmail.com。",
    ],
  },
];

const SECTIONS_EN: LegalSection[] = [
  {
    heading: "Q1: Do you store my course-selection password?",
    paragraphs: [
      "No — in no form whatsoever: no plaintext, no hashes, no “remember me”. The password is used from memory only during sign-in and submission confirm, then discarded. The selcrs cookie issued by the school is treated as a credential: Redis memory layer only, short TTL (sliding 30 minutes, hard cap 2 hours), never in the database or any log. Details in the Privacy Policy.",
    ],
  },
  {
    heading: "Q2: I heard the default password is the last six digits of my national ID. Should I do anything?",
    paragraphs: [
      "Yes. The school system's initial password is exactly that; if you have never changed it, anyone holding your student number plus those digits can sign in as you. Go change it to a strong password on the school system right away. This site cannot change it for you and accepts no password custody.",
    ],
  },
  {
    heading: "Q3: Why did my account get locked for 15 minutes?",
    paragraphs: [
      "Five wrong-password determinations by the school for the same student within 15 minutes trigger a fixed 15-minute lock. During the lock the site refuses locally and stops sending attempts, and a successful sign-in does NOT clear the failure record. The mechanism protects this site only — the school runs its own independent anomaly detection and locks; if you are locked on the school side, please contact the school.",
    ],
  },
  {
    heading: "Q4: Someone keeps deliberately triggering my lock and I can't use the site. What now?",
    paragraphs: [
      "This is a known abuse pattern (targeted lockout): roughly 5 bad attempts every 15 minutes keeps one student number nearly permanently locked. We count lock events in de-identified form and apply an operator SOP — we announce anomalies and respond when counts spike. Please switch to a strong password and watch for school-side notices too.",
    ],
  },
  {
    heading: "Q5: Why does the whole site sometimes become read-only?",
    paragraphs: [
      "When the school system fails or responds abnormally across consecutive attempts, the breaker opens and the site enters read-only safe mode: browsing and timetable keep working, sign-in and submissions pause, with a clear notice at the top. Once the school recovers and passes liveness checks, service resumes automatically — nothing for you to do.",
    ],
  },
  {
    heading: "Q6: Where does the course data come from, and how often is it updated?",
    paragraphs: [
      "Everything comes from the public course-query pages of the NSYSU course-selection system (no sign-in needed): hourly on normal days, every 10 minutes during selection windows. If a sync fails, the last successful snapshot stays in service with its update time announced at the top of the page.",
    ],
  },
  {
    heading: "Q7: Is this an official school service?",
    paragraphs: [
      "No. This is a student-built, third-party helper with no school mandate or endorsement. Formal information and selection records live at the NSYSU course-selection system.",
    ],
  },
  {
    heading: "Q8: How do I contact you or report a problem?",
    paragraphs: [
      "Two channels: open an issue on the GitHub repo (https://github.com/SenCha930511/nsysu_crs), or email sencha930511@gmail.com.",
    ],
  },
];

function FaqPage() {
  const { lang, tx } = useI18n();
  return (
    <LegalPage
      title={tx("常見問題", "FAQ")}
      intro={tx(
        "密碼怎麼被對待、鎖定與限速的目的、唯讀模式是什麼、資料從哪來——這裡一次說清楚。",
        "How passwords are treated, what locks and rate limits are for, what read-only mode means, and where the data comes from — all in one place.",
      )}
      sections={lang === "en" ? SECTIONS_EN : SECTIONS_ZH}
    />
  );
}

export default FaqPage;
