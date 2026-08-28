import {
  BoxArrowRight,
  CalendarWeek,
  Envelope,
  Github,
  Globe2,
  Layers,
  PersonCircle,
  Send,
} from "react-bootstrap-icons";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import DegradeBanner from "./DegradeBanner";
import { LangToggle, useI18n } from "../lib/i18n";
import { useAuth } from "../state/auth";
import { usePlansSync } from "../state/plansSync";

function AppShell() {
  const { tx } = useI18n();
  const { status, studentNo, logout } = useAuth();
  const { plans, activePlanId } = usePlansSync();
  const activePlan = plans.find((p) => p.id === activePlanId) ?? null;

  const NAV_LINKS = [
    { to: "/", label: tx("查課・課表", "Courses • Timetable"), icon: CalendarWeek, end: true },
    { to: "/plans", label: tx("方案實驗室", "Plan Lab"), icon: Layers, end: false },
    { to: "/write", label: tx("紀錄", "Records"), icon: Send, end: false },
  ];
  const navigate = useNavigate();

  const onLogout = () => {
    void logout().then(() => navigate("/"));
  };

  return (
    <div className="min-vh-100 d-flex flex-column">
      <DegradeBanner />
      
      {/* Top App Bar */}
      <div className="studio-header-wrapper">
        <header className="floating-navbar">
          {/* Left: Brand & Semester & Active Plan */}
          <div className="d-flex align-items-center gap-3 flex-shrink-0">
            <NavLink to="/" className="brand-badge-logo me-1">
              <div className="brand-icon-box p-0 overflow-hidden">
                <img src="/logo.png" alt={tx("中山選課 Studio logo", "NSYSU Course Studio logo")} className="brand-logo-img" />
              </div>
              <span className="d-none d-sm-inline">{tx("中山選課 Studio", "NSYSU Course Studio")}</span>
              <span className="d-sm-none">{tx("選課 Studio", "Course Studio")}</span>
            </NavLink>
            <span className="semester-pill ms-1">115-1</span>

            {status === "authed" && activePlan !== null && (
              <span className="badge text-bg-light border text-muted d-none d-xl-inline-flex align-items-center gap-1 font-monospace" style={{ fontSize: "0.8rem", padding: "0.32rem 0.65rem" }}>
                <span>{tx("方案：", "Plan:")}</span>
                <strong className="text-teal-700">{activePlan.name}</strong>
              </span>
            )}
          </div>

          {/* Center: Prominent Navigation Tabs (signed-in only) */}
          {status === "authed" && (
            <nav className="studio-nav-pills mx-auto" aria-label={tx("主要選單", "Primary navigation")}>
              {NAV_LINKS.map((link) => {
                const Icon = link.icon;
                return (
                  <NavLink
                    key={link.to}
                    to={link.to}
                    end={link.end}
                    className={({ isActive }) =>
                      `studio-nav-link${isActive ? " studio-nav-link-active" : ""}`
                    }
                  >
                    <Icon size={16} />
                    <span>{link.label}</span>
                  </NavLink>
                );
              })}
            </nav>
          )}

          {/* Right: GitHub & User Auth */}
          <div className="d-flex align-items-center justify-content-end gap-2.5 flex-shrink-0">
            <div className="user-status-card">
              <a
                href="https://github.com/SenCha930511/nsysu_crs"
                target="_blank"
                rel="noopener noreferrer"
                className="navbar-action-btn navbar-action-btn-github"
                title={tx("GitHub 原始碼倉庫", "Source code on GitHub")}
                aria-label={tx("GitHub 原始碼倉庫", "Source code on GitHub")}
              >
                <Github size={16} />
                <span>GitHub</span>
              </a>
              {status === "authed" && studentNo !== null ? (
                <>
                  <div className="user-avatar-chip" data-testid="student-no">
                    <PersonCircle size={16} className="text-teal-600 me-1" />
                    <span>{studentNo}</span>
                  </div>
                  <button
                    type="button"
                    className="navbar-action-btn navbar-action-btn-github"
                    onClick={onLogout}
                    title={tx("登出系統", "Sign out of the system")}
                  >
                    <BoxArrowRight size={15} />
                    <span className="d-none d-md-inline">{tx("登出", "Sign out")}</span>
                  </button>
                </>
              ) : status === "anon" ? (
                <NavLink
                  to="/login"
                  className="navbar-action-btn navbar-action-btn-login"
                >
                  <PersonCircle size={16} />
                  <span>{tx("登入", "Sign in")}</span>
                </NavLink>
              ) : null}
            </div>
          </div>
        </header>
      </div>

      {/* Main Studio Canvas */}
      <main className="studio-main-canvas flex-grow-1">
        <Outlet />
      </main>

      {/* Footer */}
      <footer className="small text-muted text-center py-4 mt-4 border-top bg-white">
        {/* Language Switcher */}
        <div className="mb-2.5 d-flex align-items-center justify-content-center gap-2">
          <Globe2 size={15} className="text-teal-600" />
          <LangToggle />
        </div>

        <div className="mb-1.5">
          <NavLink to="/privacy" className="text-muted text-decoration-none mx-2 hover-underline">
            {tx("隱私權政策", "Privacy Policy")}
          </NavLink>
          <span>·</span>
          <NavLink to="/tos" className="text-muted text-decoration-none mx-2 hover-underline">
            {tx("服務條款", "Terms of Service")}
          </NavLink>
          <span>·</span>
          <NavLink to="/faq" className="text-muted text-decoration-none mx-2 hover-underline">
            {tx("常見問題", "FAQ")}
          </NavLink>
          <span>·</span>
          <a
            href="https://github.com/SenCha930511/nsysu_crs"
            target="_blank"
            rel="noopener noreferrer"
            className="text-muted text-decoration-none mx-2 hover-underline"
          >
            GitHub
          </a>
        </div>
        <div className="mb-1.5 d-flex align-items-center justify-content-center gap-1 text-muted" style={{ fontSize: "0.82rem" }}>
          <span>{tx("聯絡開發者：", "Contact me:")}</span>
          <a
            href="https://github.com/SenCha930511/nsysu_crs"
            target="_blank"
            rel="noopener noreferrer"
            className="text-muted text-decoration-none d-inline-flex align-items-center gap-1 hover-underline"
          >
            <Github size={13} />
            <span>{tx("提 GitHub issue", "Open a GitHub issue")}</span>
          </a>
          <span>·</span>
          <a
            href="mailto:sencha930511@gmail.com"
            className="text-muted text-decoration-none d-inline-flex align-items-center gap-1 hover-underline"
          >
            <Envelope size={13} />
            <span>sencha930511@gmail.com</span>
          </a>
        </div>
        <div className="text-secondary" style={{ fontSize: "0.78rem" }}>
          {tx(
            "國立中山大學學生自建選課工作台 · 非官方服務",
            "Student-built course workbench for NSYSU · Unofficial service",
          )}
        </div>
      </footer>
    </div>
  );
}

export default AppShell;
