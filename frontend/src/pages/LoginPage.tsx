/**
 * /login: student id + password ONLY (SSO2 - there is deliberately no
 * captcha field anywhere in this flow). Error mapping follows the school
 * verdict taxonomy: 401 invalid_credentials / 429|423 locked (with the
 * retry hint when the body carries it) / 503 school_unavailable; everything
 * else is a generic network-ish failure. Successful login returns to the
 * guarded page that bounced the visitor here.
 */

import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useLocation, useNavigate, useSearchParams, Link } from "react-router-dom";

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
    <div className="row justify-content-center">
      <div className="col-12 col-md-8 col-lg-5">
        <div className="card login-card">
          <div className="card-body">
            <h2 className="h5 card-title fw-bold mb-1">學生登入</h2>
            <p className="text-muted small mb-3">
              使用中山選課系統帳號密碼登入（SSO，免驗證碼）。
              密碼僅用於當次驗證，本站不留存任何密碼。
            </p>

            {notice !== null && (
              <div
                className={`alert ${
                  searchParams.get("reason") === "expired"
                    ? "alert-warning"
                    : "alert-info"
                } py-2 small`}
                role="alert"
                data-testid="login-notice"
              >
                {notice}
              </div>
            )}
            {errorText !== null && (
              <div className="alert alert-danger py-2 small" role="alert">
                {errorText}
                {errorText === "學校系統異常，稍後再試" && (
                  <span className="d-block mt-1">
                    學校主機暫時連不上。你仍可
                    <Link to="/">瀏覽課程目錄與本機課表</Link>
                    ，登入相關功能暫停。
                  </span>
                )}
              </div>
            )}

            <form onSubmit={onSubmit}>
              <div className="mb-3">
                <label htmlFor="login-student-no" className="form-label">
                  學號
                </label>
                <input
                  id="login-student-no"
                  type="text"
                  className="form-control"
                  autoComplete="username"
                  value={studentNo}
                  onChange={(e) => setStudentNo(e.target.value)}
                  required
                  autoFocus
                />
              </div>
              <div className="mb-3">
                <label htmlFor="login-password" className="form-label">
                  選課密碼
                </label>
                <input
                  id="login-password"
                  type="password"
                  className="form-control"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
              </div>
              <button
                type="submit"
                className="btn btn-brand w-100"
                disabled={pending}
              >
                {pending ? "登入中…" : "登入"}
              </button>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}

export default LoginPage;
