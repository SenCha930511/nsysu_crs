import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useLocation, useNavigate, useSearchParams, Link } from "react-router-dom";
import {
  ArrowRight,
  Eye,
  EyeSlash,
  Key,
  Lock,
  Person,
  ShieldCheck,
  ShieldLock,
} from "react-bootstrap-icons";

import { ApiError } from "../lib/api";
import { loginErrorText, loginNoticeText } from "../lib/guards";
import { useAuth } from "../state/auth";

function LoginPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const [studentNo, setStudentNo] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [pending, setPending] = useState(false);
  const [errorText, setErrorText] = useState<string | null>(null);

  const notice = loginNoticeText(searchParams.get("reason"));
  const redirectTo =
    (location.state as { from?: string } | null)?.from ?? "/plans";

  useEffect(() => {
    if (auth.status === "authed") {
      navigate(redirectTo, { replace: true });
    }
  }, [auth.status, navigate, redirectTo]);

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setErrorText(null);
    auth
      .login(studentNo, password)
      .then(() => {
        navigate(redirectTo, { replace: true });
      })
      .catch((err: unknown) => {
        if (err instanceof ApiError) {
          const minutes =
            typeof err.extras.retry_after_minutes === "number"
              ? err.extras.retry_after_minutes
              : null;
          setErrorText(loginErrorText(err.status, err.detail, minutes));
        } else {
          setErrorText("網路連線異常，請稍後再試");
        }
      })
      .finally(() => setPending(false));
  };

  return (
    <div className="login-page-wrapper">
      <div className="col-12 col-sm-10 col-md-7 col-lg-5 col-xl-4" style={{ maxWidth: "440px" }}>
        <div className="login-card-pro">
          {/* Header & Logo Badge */}
          <div className="text-center mb-4">
            <div className="login-brand-icon">
              <ShieldLock size={26} />
            </div>
            <h2 className="h4 fw-bold mb-1 text-dark">學生登入</h2>
            <p className="text-muted small mb-0">
              使用國立中山大學選課系統帳號密碼登入
            </p>
          </div>

          {/* Notices & Alerts */}
          {notice !== null && (
            <div
              className={`alert ${
                searchParams.get("reason") === "expired"
                  ? "alert-warning"
                  : "alert-info"
              } py-2 px-3 small rounded-3 mb-3 d-flex align-items-center gap-2`}
              role="alert"
              data-testid="login-notice"
            >
              <Key size={15} className="flex-shrink-0" />
              <span>{notice}</span>
            </div>
          )}

          {errorText !== null && (
            <div className="alert alert-danger py-2 px-3 small rounded-3 mb-3" role="alert">
              <div className="fw-semibold mb-1">{errorText}</div>
              {errorText === "學校系統異常，稍後再試" && (
                <span className="d-block text-secondary" style={{ fontSize: "0.78rem" }}>
                  學校主機暫時連不上。你仍可
                  <Link to="/" className="fw-bold text-danger text-decoration-underline ms-1">
                    瀏覽課程目錄與本機課表
                  </Link>
                  ，登入相關功能暫停。
                </span>
              )}
            </div>
          )}

          {/* Login Form */}
          <form onSubmit={onSubmit}>
            {/* Student Number Input */}
            <div className="mb-3">
              <label htmlFor="login-student-no" className="form-label small fw-bold text-dark mb-1.5 d-flex justify-content-between">
                <span>學號 (Student ID)</span>
                <span className="text-muted fw-normal" style={{ fontSize: "0.74rem" }}>如：B113040001</span>
              </label>
              <div className="login-input-group">
                <input
                  id="login-student-no"
                  type="text"
                  className="login-input-pro"
                  placeholder="請輸入學號…"
                  autoComplete="username"
                  value={studentNo}
                  onChange={(e) => setStudentNo(e.target.value)}
                  required
                  autoFocus
                />
                <Person className="login-input-icon" />
              </div>
            </div>

            {/* Password Input */}
            <div className="mb-4">
              <label htmlFor="login-password" className="form-label small fw-bold text-dark mb-1.5 d-flex justify-content-between">
                <span>選課密碼 (Password)</span>
                <span className="text-muted fw-normal" style={{ fontSize: "0.74rem" }}>與學校選課系統相同</span>
              </label>
              <div className="login-input-group">
                <input
                  id="login-password"
                  type={showPassword ? "text" : "password"}
                  className="login-input-pro"
                  placeholder="請輸入選課密碼…"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
                <Lock className="login-input-icon" />
                <button
                  type="button"
                  className="password-toggle-btn"
                  onClick={() => setShowPassword(!showPassword)}
                  title={showPassword ? "隱藏密碼" : "顯示密碼"}
                  tabIndex={-1}
                >
                  {showPassword ? <EyeSlash size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>

            {/* Submit Button */}
            <button
              type="submit"
              className="btn-brand-login w-100"
              disabled={pending}
            >
              {pending ? (
                <>
                  <span className="spinner-border spinner-border-sm me-1" role="status" aria-hidden />
                  <span>身分驗證中…</span>
                </>
              ) : (
                <>
                  <span>立即登入</span>
                  <ArrowRight size={16} />
                </>
              )}
            </button>
          </form>

          {/* Security Features & Privacy Highlights */}
          <div className="pt-4 mt-4 border-top">
            <div className="d-flex align-items-center justify-content-center gap-2 flex-wrap mb-3">
              <span className="login-security-badge">
                <ShieldCheck size={13} className="text-teal-600" />
                <span>密碼絕不儲存</span>
              </span>
              <span className="login-security-badge">
                <Key size={13} className="text-teal-600" />
                <span>自動辨識驗證碼</span>
              </span>
            </div>

            <div className="text-center">
              <Link to="/" className="text-muted small text-decoration-none hover-underline" style={{ fontSize: "0.78rem" }}>
                ← 先不登入，直接瀏覽課表與課程目錄
              </Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default LoginPage;
