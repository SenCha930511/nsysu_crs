import {
  BookmarkCheck,
  BoxArrowRight,
  CalendarWeek,
  Layers,
  PersonCircle,
  Send,
} from "react-bootstrap-icons";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import DegradeBanner from "./DegradeBanner";
import { useAuth } from "../state/auth";

const NAV_LINKS = [
  { to: "/", label: "查課·課表", icon: CalendarWeek, end: true },
  { to: "/plans", label: "課表組合", icon: Layers, end: false },
  { to: "/selected", label: "我的已選", icon: BookmarkCheck, end: false },
  { to: "/write", label: "送單中心", icon: Send, end: false },
];

function AppShell() {
  const { status, studentNo, logout } = useAuth();
  const navigate = useNavigate();

  const onLogout = () => {
    void logout().then(() => navigate("/"));
  };

  return (
    <>
      <DegradeBanner />
      <header className="app-header">
        <div className="d-flex align-items-center gap-2">
          <NavLink to="/" className="app-header-brand">
            <h1 className="app-header-title">
              <span>中山選課小幫手</span>
              <span className="app-header-badge d-none d-sm-inline">115-1</span>
            </h1>
          </NavLink>
        </div>

        <nav className="app-nav" aria-label="主選單">
          {NAV_LINKS.map((link) => {
            const Icon = link.icon;
            return (
              <NavLink
                key={link.to}
                to={link.to}
                end={link.end}
                className={({ isActive }) =>
                  `app-nav-link${isActive ? " app-nav-link-active" : ""}`
                }
              >
                <Icon size={14} />
                <span>{link.label}</span>
              </NavLink>
            );
          })}
        </nav>

        <div className="ms-auto d-flex align-items-center gap-2">
          {status === "authed" && studentNo !== null ? (
            <>
              <div className="user-chip" data-testid="student-no">
                <PersonCircle size={15} />
                <span>{studentNo}</span>
              </div>
              <button
                type="button"
                className="btn btn-sm btn-outline-light d-inline-flex align-items-center gap-1 rounded-pill px-2.5"
                onClick={onLogout}
                title="登出系統"
              >
                <BoxArrowRight size={14} />
                <span className="d-none d-sm-inline">登出</span>
              </button>
            </>
          ) : status === "anon" ? (
            <NavLink
              to="/login"
              className="btn btn-sm btn-light text-teal-800 fw-bold rounded-pill px-3 shadow-sm d-inline-flex align-items-center gap-1"
            >
              <PersonCircle size={14} />
              <span>登入</span>
            </NavLink>
          ) : null}
        </div>
      </header>
      <main className="container-fluid px-3 py-3">
        <Outlet />
      </main>
      <footer className="small text-secondary text-center py-4 mt-4 border-top">
        <div className="mb-2">
          <NavLink to="/privacy" className="link-secondary text-decoration-none mx-2">
            隱私權政策
          </NavLink>
          <span className="text-muted">·</span>
          <NavLink to="/tos" className="link-secondary text-decoration-none mx-2">
            服務條款
          </NavLink>
          <span className="text-muted">·</span>
          <NavLink to="/faq" className="link-secondary text-decoration-none mx-2">
            常見問題
          </NavLink>
        </div>
        <div className="text-muted" style={{ fontSize: "0.78rem" }}>
          本站為學生自建之開源選課輔助工具，非國立中山大學官方服務。
        </div>
      </footer>
    </>
  );
}

export default AppShell;

