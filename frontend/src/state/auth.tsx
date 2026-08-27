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

export interface AuthContextValue {
  status: AuthStatus;
  /** True after a soft logout (a 401 ended the session, not the user). */
  expired: boolean;
  studentNo: string | null;
  login: (studentNo: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [expired, setExpired] = useState(false);
  const [studentNo, setStudentNo] = useState<string | null>(null);
  const statusRef = useRef(status);
  statusRef.current = status;

  useEffect(() => {
    let cancelled = false;
    fetchMe()
      .then((body) => {
        if (cancelled) return;
        setStudentNo(body.student_no);
        setStatus("authed");
      })
      .catch(() => {
        if (cancelled) return;
        setStudentNo(null);
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
    setExpired(false);
    setStatus("authed");
  }, []);

  const doLogout = useCallback(async () => {
    try {
      await logout();
    } finally {
      setStudentNo(null);
      setExpired(false);
      setStatus("anon");
    }
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ status, expired, studentNo, login: doLogin, logout: doLogout }),
    [status, expired, studentNo, doLogin, doLogout],
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
