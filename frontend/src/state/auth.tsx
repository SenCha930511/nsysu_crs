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
  /** REGWEB-family features (payment, enrollment cert) connected on the account. */
  regwebAvailable: boolean;
  /** SCO-family features (歷年成績 grades) connected on the account. */
  scoAvailable: boolean;
  /** True when the server's stu_enroll family is enabled (from /api/auth/me). */
  featureStuEnroll: boolean;
  /** Ends the whole session (soft logout + expired notice) - used by guards
   * and by the /me zombie-session detector. */
  requireRelogin: () => void;
  login: (studentNo: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [expired, setExpired] = useState(false);
  const [studentNo, setStudentNo] = useState<string | null>(null);
  const [csrfToken, setCsrfToken] = useState<string | null>(null);
  const [regwebAvailable, setRegwebAvailable] = useState(false);
  const [scoAvailable, setScoAvailable] = useState(false);
  const [featureStuEnroll, setFeatureStuEnroll] = useState(false);
  const statusRef = useRef(status);
  statusRef.current = status;

  useEffect(() => {
    let cancelled = false;
    fetchMe()
      .then((body) => {
        if (cancelled) return;
        setStudentNo(body.student_no);
        setRegwebAvailable(body.regweb_available);
        setScoAvailable(body.sco_available);
        setFeatureStuEnroll(body.feature_stu_enroll);
        // A refresh survives via sessionStorage: the csrf cookie value is
        // unchanged by page reloads (the backend re-sets the SAME value).
        setCsrfToken(readStoredCsrfToken());
        setStatus("authed");
      })
      .catch(() => {
        if (cancelled) return;
        setStudentNo(null);
        setCsrfToken(null);
        setRegwebAvailable(false);
        setScoAvailable(false);
        setStatus("anon");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const softLogout = useCallback(() => {
    setStudentNo(null);
    setCsrfToken(null);
    storeCsrfToken(null);
    setRegwebAvailable(false);
    setScoAvailable(false);
    setFeatureStuEnroll(false);
    setStatus("anon");
    setExpired(true);
    logout().catch(() => {
      // best-effort server-side cleanup; the session is already unusable
    });
  }, []);

  // Global 401 seam: soft logout; the guard turns the state into a route.
  useEffect(() => {
    bindUnauthorizedHandler((detail) => {
      if (!shouldSoftLogout(statusRef.current, detail)) return;
      softLogout();
    });
    return () => bindUnauthorizedHandler(null);
  }, [softLogout]);

  const pendingPollRef = useRef<number | null>(null);
  const stopStuPendingPoll = useCallback(() => {
    if (pendingPollRef.current !== null) {
      window.clearInterval(pendingPollRef.current);
      pendingPollRef.current = null;
    }
  }, []);
  useEffect(() => stopStuPendingPoll, [stopStuPendingPoll]);

  const startStuPendingPoll = useCallback(() => {
    stopStuPendingPoll();
    let ticks = 0;
    pendingPollRef.current = window.setInterval(() => {
      ticks += 1;
      const exhausted = ticks >= 6;
      void fetchMe()
        .then((me) => {
          setRegwebAvailable(me.regweb_available);
          setScoAvailable(me.sco_available);
          setFeatureStuEnroll(me.feature_stu_enroll);
          if (me.regweb_available && me.sco_available) stopStuPendingPoll();
        })
        .catch(() => {
          // best-effort: flags stay false until the next successful probe boot
        })
        .finally(() => {
          if (exhausted) stopStuPendingPoll();
        });
    }, 2500);
  }, [stopStuPendingPoll]);

  const doLogin = useCallback(async (no: string, password: string) => {
    const body = await login(no.trim(), password);
    setStudentNo(body.student_no);
    setCsrfToken(body.csrf_token);
    storeCsrfToken(body.csrf_token);
    setRegwebAvailable(body.regweb_available);
    setScoAvailable(body.sco_available);
    setExpired(false);
    setStatus("authed");
    if (body.stu_enroll_pending) startStuPendingPoll();
  }, [startStuPendingPoll]);

  const doLogout = useCallback(async () => {
    try {
      await logout();
    } finally {
      stopStuPendingPoll();
      setStudentNo(null);
      setCsrfToken(null);
      storeCsrfToken(null);
      setRegwebAvailable(false);
      setScoAvailable(false);
      setExpired(false);
      setStatus("anon");
    }
  }, [stopStuPendingPoll]);

  const requireRelogin = softLogout;

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      expired,
      studentNo,
      csrfToken,
      regwebAvailable,
      scoAvailable,
      featureStuEnroll,
      login: doLogin,
      logout: doLogout,
      requireRelogin,
    }),
    [
      status,
      expired,
      studentNo,
      csrfToken,
      regwebAvailable,
      scoAvailable,
      featureStuEnroll,
      doLogin,
      doLogout,
      requireRelogin,
    ],
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
