/**
 * Shared layout for the legal/info pages (/privacy, /tos, /faq; todo 17):
 * a titled card per section, plus a cross-link row so the three pages stay
 * one click apart. Plain Bootstrap, no JS widgets - the CSP stays tight.
 */

import type { ReactNode } from "react";

import { Link } from "react-router-dom";

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
  return (
    <nav className="small text-center my-3" aria-label="法律資訊">
      <Link to="/privacy">隱私權政策</Link>
      <span className="text-secondary mx-2">·</span>
      <Link to="/tos">服務條款</Link>
      <span className="text-secondary mx-2">·</span>
      <Link to="/faq">常見問題</Link>
      <span className="text-secondary mx-2">·</span>
      <Link to="/">回到查課</Link>
    </nav>
  );
}

function LegalPage({ title, intro, sections, children }: LegalPageProps) {
  return (
    <div className="row justify-content-center">
      <div className="col-12 col-lg-9 col-xl-8">
        <div className="card shadow-sm mb-3">
          <div className="card-body">
            <h1 className="h4 card-title">{title}</h1>
            {intro !== undefined && <p className="text-secondary small mb-0">{intro}</p>}
          </div>
        </div>
        {sections.map((section) => (
          <div className="card shadow-sm mb-3" key={section.heading}>
            <div className="card-body">
              <h2 className="h6 card-title fw-bold">{section.heading}</h2>
              {section.paragraphs?.map((text) => (
                <p className="card-text small mb-2" key={text.slice(0, 24)}>
                  {text}
                </p>
              ))}
              {section.list !== undefined && (
                <ul className="small mb-0">
                  {section.list.map((item) => (
                    <li key={item.slice(0, 24)}>{item}</li>
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
