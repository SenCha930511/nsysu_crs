import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useLocation, useNavigate, useSearchParams, Link } from "react-router-dom";
import { ShieldCheck } from "react-bootstrap-icons";

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
    <div className="login-card-container">
      <div className="col-12 col-md-7 col-lg-5 col-xl-4">
        <div className="login-card">
          <div className="text-center mb-3">
            <div
              className="d-inline-flex align-items-center justify-content-center bg-teal-50 text-teal-600 rounded-circle mb-2"
              style={{ width: "48px", height: "48px" }}
            >
              <ShieldCheck size={26} />
            </div>
            <h2 className="h5 fw-bold mb-1 text-dark">學生登入</h2>
            <p className="text-muted small mb-0">
              使用中山選課系統帳號密碼登入（SSO，免驗證碼）
            </p>
          </div>

          {notice !== null && (
            <div
              className={`alert ${
                searchParams.get("reason") === "expired"
                  ? "alert-warning"
                  : "alert-info"
              } py-2 px-3 small rounded-3 mb-3`}
              role="alert"
              data-testid="login-notice"
            >
              {notice}
            </div>
          )}
          {errorText !== null && (
            <div className="alert alert-danger py-2 px-3 small rounded-3 mb-3" role="alert">
              {errorText}
              {errorText === "學校系統異常，稍後再試" && (
                <span className="d-block mt-1">
                  學校主機暫時連不上。你仍可
                  <Link to="/" className="fw-semibold text-danger text-decoration-underline ms-1">
                    瀏覽課程目錄與本機課表
                  </Link>
                  ，登入相關功能暫停。
                </span>
              )}
            </div>
          )}

          <form onSubmit={onSubmit}>
            <div className="mb-3">
              <label htmlFor="login-student-no" className="form-label small fw-semibold text-dark mb-1">
                學號
              </label>
              <div className="position-relative">
                <input
                  id="login-student-no"
                  type="text"
                  className="form-control"
                  placeholder="例如：B113040001"
                  autoComplete="username"
                  value={studentNo}
                  onChange={(e) => setStudentNo(e.target.value)}
                  required
                  autoFocus
                />
              </div>
            </div>
            <div className="mb-4">
              <label htmlFor="login-password" className="form-label small fw-semibold text-dark mb-1">
                選課密碼
              </label>
              <div className="position-relative">
                <input
                  id="login-password"
                  type="password"
                  className="form-control"
                  placeholder="請輸入選課密碼"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
              </div>
            </div>
            <button
              type="submit"
              className="btn btn-brand w-100 py-2"
              disabled={pending}
            >
              {pending ? "登入中…" : "立即登入"}
            </button>
          </form>
          <div className="text-center mt-3">
            <span className="text-muted" style={{ fontSize: "0.74rem" }}>
              🔒 密碼僅用於當次單向驗證，本站絕不留存任何密碼
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

export default LoginPage;

