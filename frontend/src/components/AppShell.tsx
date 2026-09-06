import {
  BoxArrowRight,
  CalendarCheck,
  CalendarWeek,
  Envelope,
  Github,
  Globe2,
  PersonCircle,
  Search,
  Send,
} from "react-bootstrap-icons";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate, useSearchParams } from "react-router-dom";

import DegradeBanner from "./DegradeBanner";
import { fetchCatalogMeta } from "../lib/api";
import { LangToggle, useI18n } from "../lib/i18n";
import { formatSemesterLabel } from "../lib/semesterLabel";
import { useAuth } from "../state/auth";
import { useSelection } from "../state/selection";

function AppShell() {
  const { tx } = useI18n();
  const { status, studentNo, logout } = useAuth();
  const { selected } = useSelection();
  const [semester, setSemester] = useState<string | null>(null);
  const location = useLocation();
  const [searchParams] = useSearchParams();

  const viewParam = searchParams.get("view");
  const isBrowseActive =
    location.pathname === "/" && (viewParam === "browse" || !viewParam);
  const isScheduleActive =
    location.pathname === "/" &&
    (viewParam === "schedule" || viewParam === "selections" || viewParam === "timetable");

  useEffect(() => {
    let alive = true;
    fetchCatalogMeta()
      .then((meta) => {
        if (alive && meta.year_sem !== null) {
          setSemester(formatSemesterLabel(meta.year_sem));
        }
      })
      .catch(() => {
        // Degrade by absence: an unreachable meta endpoint hides the pill.
      });
    return () => {
      alive = false;
    };
  }, []);

  const NAV_LINKS = [
    { to: "/", label: tx("查課・課表", "Courses • Timetable"), icon: CalendarWeek, end: true },
    { to: "/write", label: tx("紀錄", "Records"), icon: Send, end: false },
    { to: "/me", label: tx("我的資料", "Profile"), icon: PersonCircle, end: false },
  ];
  const navigate = useNavigate();

  const onLogout = () => {
    void logout().then(() => navigate("/"));
  };

  return (
    <div className="min-vh-100 d-flex flex-column">
      {/* Top App Bar */}
      <div className="studio-header-wrapper">
        <DegradeBanner />
        <header className="floating-navbar">
          {/* Left: Brand & Semester */}
          <div className="d-flex align-items-center gap-2 gap-sm-3 flex-shrink-0 floating-navbar-brand">
            <NavLink to="/" className="brand-badge-logo me-1">
              <div className="brand-icon-box p-0 overflow-hidden">
                <img src="/logo.png" alt={tx("中山選課 Studio logo", "NSYSU Course Studio logo")} className="brand-logo-img" />
              </div>
              <span className="d-none d-sm-inline">{tx("中山選課 Studio", "NSYSU Course Studio")}</span>
              <span className="d-sm-none">{tx("選課 Studio", "Course Studio")}</span>
            </NavLink>
            {semester !== null && <span className="semester-pill ms-1">{semester}</span>}
          </div>

          {/* Center on Desktop: Segmented Navigation Tabs */}
          <nav className="studio-nav-pills mx-auto d-none d-md-flex" aria-label={tx("主要選單", "Primary navigation")}>
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

          {/* Right: GitHub & User Auth */}
          <div className="d-flex align-items-center justify-content-end flex-shrink-0 floating-navbar-auth" style={{ gap: "0.45rem" }}>
            <div className="user-status-card">
              <a
                href="https://github.com/SenCha930511/nsysu_crs"
                target="_blank"
                rel="noopener noreferrer"
                className="navbar-action-btn navbar-action-btn-github"
                title={tx("GitHub 原始碼倉庫", "Source code on GitHub")}
                aria-label={tx("GitHub 原始碼倉庫", "Source code on GitHub")}
              >
                <Github size={15} />
                <span className="d-none d-lg-inline">GitHub</span>
              </a>
              {status === "authed" && studentNo !== null ? (
                <>
                  <div className="user-avatar-chip" data-testid="student-no">
                    <PersonCircle size={15} className="text-teal-600 me-1 flex-shrink-0" />
                    <span>{studentNo}</span>
                  </div>
                  <button
                    type="button"
                    className="navbar-action-btn navbar-action-btn-github navbar-action-btn-logout"
                    onClick={onLogout}
                    title={tx("登出系統", "Sign out of the system")}
                    aria-label={tx("登出系統", "Sign out")}
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
                  <PersonCircle size={15} />
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

      {/* Mobile Native-Style Bottom Tab Bar (< md) */}
      <nav className="mobile-bottom-nav d-md-none" aria-label={tx("行動版底部導覽", "Mobile navigation")}>
        <NavLink
          to="/?view=browse"
          className={() => `mobile-tab-item ${isBrowseActive ? "active" : ""}`}
          onClick={(e) => {
            if (location.pathname === "/") {
              e.preventDefault();
              navigate("/?view=browse");
            }
          }}
        >
          <div className="mobile-tab-icon-wrapper">
            <Search size={18} />
          </div>
          <span className="mobile-tab-label">{tx("查課", "Courses")}</span>
        </NavLink>

        <NavLink
          to="/?view=schedule"
          className={() => `mobile-tab-item ${isScheduleActive ? "active" : ""}`}
          onClick={(e) => {
            if (location.pathname === "/") {
              e.preventDefault();
              navigate("/?view=schedule");
            }
          }}
        >
          <div className="mobile-tab-icon-wrapper">
            <CalendarCheck size={18} />
            {selected.length > 0 && <span className="mobile-tab-badge">{selected.length}</span>}
          </div>
          <span className="mobile-tab-label">{tx("課表", "Timetable")}</span>
        </NavLink>

        <NavLink
          to="/write"
          className={({ isActive }) => `mobile-tab-item ${isActive ? "active" : ""}`}
        >
          <div className="mobile-tab-icon-wrapper">
            <Send size={18} />
          </div>
          <span className="mobile-tab-label">{tx("紀錄", "Records")}</span>
        </NavLink>

        <NavLink
          to="/me"
          className={({ isActive }) => `mobile-tab-item ${isActive ? "active" : ""}`}
        >
          <div className="mobile-tab-icon-wrapper">
            <PersonCircle size={18} />
          </div>
          <span className="mobile-tab-label">{tx("我的資料", "Profile")}</span>
        </NavLink>
      </nav>

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
        <div className="mb-1.5 d-flex align-items-center justify-content-center flex-wrap gap-1 px-3 text-muted" style={{ fontSize: "0.82rem" }}>
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
          <span className="d-none d-sm-inline">·</span>
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
