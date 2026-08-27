/**
 * Shared chrome: degrade banner + brand header with nav + auth corner,
 * then the routed page. Header/nav reuse the todo-10 brand tokens; nav is
 * plain links (no dropdown JS), matching the native-tooltip debt note.
 */

import { BoxArrowRight, PersonCircle } from "react-bootstrap-icons";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import DegradeBanner from "./DegradeBanner";
import { useAuth } from "../state/auth";

const NAV_LINKS = [
  { to: "/", label: "查課·課表", end: true },
  { to: "/plans", label: "課表組合", end: false },
  { to: "/selected", label: "我的已選", end: false },
  { to: "/write", label: "送單中心", end: false },
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
        <h1 className="h5 mb-0 fw-bold text-white">
          <NavLink to="/" className="text-white text-decoration-none">
            中山選課小幫手
          </NavLink>
        </h1>
        <span className="app-header-sub small d-none d-md-inline">
          NSYSU Course Wrapper · 115-1
        </span>
        <nav className="app-nav" aria-label="主選單">
          {NAV_LINKS.map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              end={link.end}
              className={({ isActive }) =>
                `app-nav-link${isActive ? " app-nav-link-active" : ""}`
              }
            >
              {link.label}
            </NavLink>
          ))}
        </nav>
        <div className="ms-auto d-flex align-items-center gap-2">
          {status === "authed" && studentNo !== null ? (
            <>
              <span className="text-white small" data-testid="student-no">
                <PersonCircle className="me-1" />
                {studentNo}
              </span>
              <button
                type="button"
                className="btn btn-sm btn-outline-light"
                onClick={onLogout}
              >
                <BoxArrowRight className="me-1" />
                登出
              </button>
            </>
          ) : status === "anon" ? (
            <NavLink to="/login" className="btn btn-sm btn-outline-light">
              登入
            </NavLink>
          ) : null}
        </div>
      </header>
      <main className="container-fluid px-3 py-3">
        <Outlet />
      </main>
    </>
  );
}

export default AppShell;
