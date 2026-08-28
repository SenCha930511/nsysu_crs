import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

export type Lang = "zh" | "en";

interface I18nValue {
  lang: Lang;
  setLang: (next: Lang) => void;
  /** Plain-string bilingual picker: tx("中文", "English"). */
  tx: (zh: string, en: string) => string;
}

const I18nContext = createContext<I18nValue | null>(null);
const STORAGE_KEY = "crs-lang";

function initialLang(): Lang {
  try {
    return typeof localStorage !== "undefined" && localStorage.getItem(STORAGE_KEY) === "en"
      ? "en"
      : "zh";
  } catch {
    return "zh";
  }
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(initialLang);

  useEffect(() => {
    document.documentElement.lang = lang === "zh" ? "zh-Hant" : "en";
    try {
      localStorage.setItem(STORAGE_KEY, lang);
    } catch {
      // storage unavailable (private mode): the choice stays in-memory only.
    }
  }, [lang]);

  const setLang = useCallback((next: Lang) => setLangState(next), []);
  const tx = useCallback((zh: string, en: string) => (lang === "zh" ? zh : en), [lang]);
  const value = useMemo(() => ({ lang, setLang, tx }), [lang, setLang, tx]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nValue {
  const value = useContext(I18nContext);
  if (value === null) {
    throw new Error("useI18n must be used inside <I18nProvider>");
  }
  return value;
}

export function LangToggle() {
  const { lang, setLang, tx } = useI18n();
  return (
    <div
      className="btn-group btn-group-sm rounded-pill border overflow-hidden"
      role="group"
      aria-label={tx("語言切換", "Language switch")}
    >
      <button
        type="button"
        className={`btn ${lang === "zh" ? "btn-brand" : "btn-outline-secondary border-0"} px-2 py-1`}
        style={{ fontSize: "0.75rem", fontWeight: 700 }}
        onClick={() => setLang("zh")}
        aria-pressed={lang === "zh"}
      >
        中
      </button>
      <button
        type="button"
        className={`btn ${lang === "en" ? "btn-brand" : "btn-outline-secondary border-0"} px-2 py-1`}
        style={{ fontSize: "0.75rem", fontWeight: 700 }}
        onClick={() => setLang("en")}
        aria-pressed={lang === "en"}
      >
        EN
      </button>
    </div>
  );
}
