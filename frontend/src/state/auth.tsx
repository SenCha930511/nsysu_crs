/**
 * Site-session auth state (todo 11): boot probe -> {loading|authed|anon},
 * login/logout actions, and the global soft-logout seam for any backend 401
 * (dead site session or dead school jar). The seam only FLIPS STATE
 * (anon + expired); the route guard is the single redirect source and shows
 * the reason=expired notice, so the two can never race.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";

import { bindUnauthorizedHandler, fetchMe, login, logout } from "../lib/api";
import { shouldSoftLogout } from "../lib/guards";
import type { AuthStatus } from "../lib/guards";

const CSRF_STORAGE_KEY = "nsysu_crs_csrf_token";

function readStoredCsrfToken(): string | null {
  try {
    return sessionStorage.getItem(CSRF_STORAGE_KEY);
  } catch {
    return null;
  }
}

function storeCsrfToken(token: string | null): void {
  try {
    if (token === null) {
      sessionStorage.removeItem(CSRF_STORAGE_KEY);
    } else {
      sessionStorage.setItem(CSRF_STORAGE_KEY, token);
    }
  } catch {
    // sessionStorage unavailable: write endpoints simply lack a token
  }
}

export interface AuthContextValue {
  status: AuthStatus;
  /** True after a soft logout (a 401 ended the session, not the user). */
  expired: boolean;
  studentNo: string | null;
  /** CSRF token for /api/write/* (from the login body; null if unrecoverable). */
  csrfToken: string | null;
  login: (studentNo: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [expired, setExpired] = useState(false);
  const [studentNo, setStudentNo] = useState<string | null>(null);
  const [csrfToken, setCsrfToken] = useState<string | null>(null);
  const statusRef = useRef(status);
  statusRef.current = status;

  useEffect(() => {
    let cancelled = false;
    fetchMe()
      .then((body) => {
        if (cancelled) return;
        setStudentNo(body.student_no);
        // A refresh survives via sessionStorage: the csrf cookie value is
        // unchanged by page reloads (the backend re-sets the SAME value).
        setCsrfToken(readStoredCsrfToken());
        setStatus("authed");
      })
      .catch(() => {
        if (cancelled) return;
        setStudentNo(null);
        setCsrfToken(null);
        setStatus("anon");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Global 401 seam: soft logout; the guard turns the state into a route.
  useEffect(() => {
    bindUnauthorizedHandler(() => {
      if (!shouldSoftLogout(statusRef.current)) return;
      setStudentNo(null);
      setCsrfToken(null);
      storeCsrfToken(null);
      setStatus("anon");
      setExpired(true);
      logout().catch(() => {
        // best-effort server-side cleanup; the session is already unusable
      });
    });
    return () => bindUnauthorizedHandler(null);
  }, []);

  const doLogin = useCallback(async (no: string, password: string) => {
    const body = await login(no.trim(), password);
    setStudentNo(body.student_no);
    setCsrfToken(body.csrf_token);
    storeCsrfToken(body.csrf_token);
    setExpired(false);
    setStatus("authed");
  }, []);

  const doLogout = useCallback(async () => {
    try {
      await logout();
    } finally {
      setStudentNo(null);
      setCsrfToken(null);
      storeCsrfToken(null);
      setExpired(false);
      setStatus("anon");
    }
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      expired,
      studentNo,
      csrfToken,
      login: doLogin,
      logout: doLogout,
    }),
    [status, expired, studentNo, csrfToken, doLogin, doLogout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (ctx === null) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return ctx;
}
