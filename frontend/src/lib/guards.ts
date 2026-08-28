/**
 * Route-guard + login-notice decision logic (pure; vitest in node env).
 *
 * Two redirect sources land on /login with a distinguishable `reason`:
 * - Never-logged-in visits to a protected path -> /login?reason=required
 * - A 401 from ANY backend call while authed (dead site session or dead
 *   school jar) -> soft logout + /login?reason=expired
 */

export type AuthStatus = "loading" | "authed" | "anon";

export const LOGIN_REASON_REQUIRED = "required";
export const LOGIN_REASON_EXPIRED = "expired";

const PROTECTED_PREFIXES = ["/plans", "/write"];

export interface GuardDecision {
  allow: boolean;
  /** Redirect target when !allow (null while still loading). */
  redirectTo: string | null;
}

/**
 * The guard is the SINGLE redirect source (the soft-logout seam only flips
 * auth state) - otherwise the seam's own Navigate and the guard race and
 * the reason param can flip. ``expired`` distinguishes the two notices.
 */
export function decideGuard(
  status: AuthStatus,
  pathname: string,
  expired = false,
): GuardDecision {
  const isProtected = PROTECTED_PREFIXES.some((prefix) => pathname.startsWith(prefix));
  if (!isProtected) return { allow: true, redirectTo: null };
  if (status === "loading") return { allow: false, redirectTo: null };
  if (status === "authed") return { allow: true, redirectTo: null };
  const reason = expired ? LOGIN_REASON_EXPIRED : LOGIN_REASON_REQUIRED;
  return { allow: false, redirectTo: `/login?reason=${reason}` };
}

/**
 * A backend 401 only means "expired" when the user WAS logged in; an
 * anonymous session's 401 (the boot /api/auth/me probe) must stay silent.
 */
export function shouldSoftLogout(statusBefore: AuthStatus): boolean {
  return statusBefore === "authed";
}

export function loginNoticeText(reason: string | null, lang: "zh" | "en" = "zh"): string | null {
  const en = lang === "en";
  switch (reason) {
    case LOGIN_REASON_EXPIRED:
      return en ? "Your sign-in session has expired. Please sign in again." : "登入階段已過期，請重新登入。";
    case LOGIN_REASON_REQUIRED:
      return en ? "This page requires sign-in." : "此頁面需要先登入。";
    default:
      return null;
  }
}

/** /login error-body -> user-facing text (SSO2 flow has no captcha field). */
export function loginErrorText(
  status: number,
  detail: string,
  retryAfterMinutes: number | null,
  lang: "zh" | "en" = "zh",
): string {
  const en = lang === "en";
  if (status === 401 && detail === "invalid_credentials") {
    return en ? "Incorrect student ID or password" : "學號或密碼錯誤";
  }
  if (status === 429) {
    if (en) {
      return retryAfterMinutes !== null
        ? `Too many attempts; account temporarily locked. Try again in about ${retryAfterMinutes} minutes`
        : "Too many attempts. Please try again shortly";
    }
    return retryAfterMinutes !== null
      ? `嘗試次數過多，帳號暫時鎖定，請約 ${retryAfterMinutes} 分鐘後再試`
      : "嘗試次數過多，請稍後再試";
  }
  if (status === 423) {
    if (en) {
      return retryAfterMinutes !== null
        ? `Account locked. Try again in about ${retryAfterMinutes} minutes`
        : "Account locked. Please try again shortly";
    }
    return retryAfterMinutes !== null
      ? `帳號已鎖定，請約 ${retryAfterMinutes} 分鐘後再試`
      : "帳號已鎖定，請稍後再試";
  }
  if (status === 503) {
    return en ? "The school system is unavailable right now" : "學校系統異常，稍後再試";
  }
  return en ? "Sign-in failed. Please try again shortly" : "登入失敗，請稍後再試";
}
