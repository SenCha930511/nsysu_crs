import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { useI18n } from "../lib/i18n";

export interface LegalSection {
  heading: string;
  paragraphs?: string[];
  list?: string[];
}

interface LegalPageProps {
  title: string;
  intro?: string;
  sections: LegalSection[];
  children?: ReactNode;
}

export function LegalCrossLinks() {
  const { tx } = useI18n();
  return (
    <nav className="small text-center my-4 p-3 bg-white rounded-4 shadow-sm border" aria-label={tx("法律資訊", "Legal information")}>
      <Link to="/privacy" className="text-teal-700 text-decoration-none fw-semibold">{tx("隱私權政策", "Privacy Policy")}</Link>
      <span className="text-muted mx-2">·</span>
      <Link to="/tos" className="text-teal-700 text-decoration-none fw-semibold">{tx("服務條款", "Terms of Service")}</Link>
      <span className="text-muted mx-2">·</span>
      <Link to="/faq" className="text-teal-700 text-decoration-none fw-semibold">{tx("常見問題", "FAQ")}</Link>
      <span className="text-muted mx-2">·</span>
      <Link to="/" className="text-teal-700 text-decoration-none fw-semibold">{tx("回到查課", "Back to courses")}</Link>
    </nav>
  );
}

function LegalPage({ title, intro, sections, children }: LegalPageProps) {
  return (
    <div className="row justify-content-center">
      <div className="col-12 col-lg-9 col-xl-8">
        <div className="card shadow-sm border-0 rounded-4 mb-3">
          <div className="card-body p-4">
            <h1 className="h4 card-title fw-bold text-dark mb-2">{title}</h1>
            {intro !== undefined && <p className="text-muted small mb-0">{intro}</p>}
          </div>
        </div>
        {sections.map((section) => (
          <div className="card shadow-sm border-0 rounded-4 mb-3" key={section.heading}>
            <div className="card-body p-4">
              <h2 className="h6 card-title fw-bold text-dark mb-2">{section.heading}</h2>
              {section.paragraphs?.map((text) => (
                <p className="card-text small text-secondary mb-2" key={text.slice(0, 24)}>
                  {text}
                </p>
              ))}
              {section.list !== undefined && (
                <ul className="small text-secondary mb-0 ps-3">
                  {section.list.map((item) => (
                    <li key={item.slice(0, 24)} className="mb-1">{item}</li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        ))}
        {children}
        <LegalCrossLinks />
      </div>
    </div>
  );
}

export default LegalPage;

