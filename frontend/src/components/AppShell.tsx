import {
  BoxArrowRight,
  CalendarWeek,
  Github,
  Layers,
  PersonCircle,
  Send,
} from "react-bootstrap-icons";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import DegradeBanner from "./DegradeBanner";
import { useAuth } from "../state/auth";
import { usePlansSync } from "../state/plansSync";

const NAV_LINKS = [
  { to: "/", label: "查課・課表", icon: CalendarWeek, end: true },
  { to: "/plans", label: "方案實驗室", icon: Layers, end: false },
  { to: "/write", label: "紀錄", icon: Send, end: false },
];

function AppShell() {
  const { status, studentNo, logout } = useAuth();
  const { plans, activePlanId } = usePlansSync();
  const activePlan = plans.find((p) => p.id === activePlanId) ?? null;
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
          {/* Brand & Semester */}
          <div className="d-flex align-items-center gap-2">
            <NavLink to="/" className="brand-badge-logo">
              <div className="brand-icon-box p-0 overflow-hidden">
                <img src="/logo.png" alt="中山選課 Studio logo" className="brand-logo-img" />
              </div>
              <span className="d-none d-sm-inline">中山選課 Studio</span>
              <span className="d-sm-none">選課 Studio</span>
            </NavLink>
            <span className="semester-pill">115-1</span>
            
            {activePlan !== null && (
              <span className="badge text-bg-light border text-muted d-none d-lg-inline-flex align-items-center gap-1 font-monospace" style={{ fontSize: "0.72rem" }}>
                <span>課表：</span>
                <strong className="text-teal-700">{activePlan.name}</strong>
              </span>
            )}
          </div>

          {/* Navigation Pills */}
          <nav className="studio-nav-pills" aria-label="主要選單">
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

          {/* User Auth Chip */}
          <div className="user-status-card">
            <a
              href="https://github.com/SenCha930511/nsysu_crs"
              target="_blank"
              rel="noopener noreferrer"
              className="btn btn-sm btn-outline-secondary rounded-pill p-1 px-2 d-inline-flex align-items-center"
              title="GitHub 原始碼倉庫"
              aria-label="GitHub 原始碼倉庫"
              style={{ fontSize: "0.75rem" }}
            >
              <Github size={13} />
            </a>
            {status === "authed" && studentNo !== null ? (
              <>
                <div className="user-avatar-chip" data-testid="student-no">
                  <PersonCircle size={14} className="text-teal-600" />
                  <span>{studentNo}</span>
                </div>
                <button
                  type="button"
                  className="btn btn-sm btn-outline-secondary rounded-pill p-1 px-2 d-inline-flex align-items-center gap-1"
                  onClick={onLogout}
                  title="登出系統"
                  style={{ fontSize: "0.75rem" }}
                >
                  <BoxArrowRight size={13} />
                  <span className="d-none d-md-inline">登出</span>
                </button>
              </>
            ) : status === "anon" ? (
              <NavLink
                to="/login"
                className="btn btn-sm btn-brand rounded-pill px-3 py-1 shadow-sm d-inline-flex align-items-center gap-1"
                style={{ fontSize: "0.82rem" }}
              >
                <PersonCircle size={14} />
                <span>登入</span>
              </NavLink>
            ) : null}
          </div>
        </header>
      </div>

      {/* Main Studio Canvas */}
      <main className="studio-main-canvas flex-grow-1">
        <Outlet />
      </main>

      {/* Footer */}
      <footer className="small text-muted text-center py-3 mt-4 border-top">
        <div className="mb-1">
          <NavLink to="/privacy" className="text-muted text-decoration-none mx-2 hover-underline">
            隱私權政策
          </NavLink>
          <span>·</span>
          <NavLink to="/tos" className="text-muted text-decoration-none mx-2 hover-underline">
            服務條款
          </NavLink>
          <span>·</span>
          <NavLink to="/faq" className="text-muted text-decoration-none mx-2 hover-underline">
            常見問題
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
        <div className="text-secondary" style={{ fontSize: "0.74rem" }}>
          國立中山大學學生自建選課工作台 · 非官方服務
        </div>
      </footer>
    </div>
  );
}

export default AppShell;
