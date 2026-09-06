import { describe, expect, it } from "vitest";

import {
  decideGuard,
  isFamilyExpiredDetail,
  shouldSoftLogout,
  shouldForceRelogin,
  loginErrorText,
  loginNoticeText,
} from "./guards";

describe("decideGuard", () => {
  it.each(["/write", "/records", "/me"])(
    "redirects anonymous visitors of %s to /login?reason=required",
    (path) => {
      expect(decideGuard("anon", path)).toEqual({
        allow: false,
        redirectTo: "/login?reason=required",
      });
    },
  );

  it("redirects to /login?reason=expired after a soft logout", () => {
    expect(decideGuard("anon", "/write", true)).toEqual({
      allow: false,
      redirectTo: "/login?reason=expired",
    });
    expect(decideGuard("anon", "/write", true).redirectTo).toBe(
      "/login?reason=expired",
    );
  });

  it("lets authed users into protected paths", () => {
    expect(decideGuard("authed", "/write")).toEqual({
      allow: true,
      redirectTo: null,
    });
  });

  it("holds (no redirect) while the session is still unknown", () => {
    expect(decideGuard("loading", "/write")).toEqual({
      allow: false,
      redirectTo: null,
    });
  });

  it("leaves public paths open for everyone", () => {
    expect(decideGuard("anon", "/")).toEqual({ allow: true, redirectTo: null });
    expect(decideGuard("anon", "/login")).toEqual({
      allow: true,
      redirectTo: null,
    });
  });
});

describe("shouldSoftLogout", () => {
  it("fires only when the user WAS authed", () => {
    expect(shouldSoftLogout("authed", "not_authenticated")).toBe(true);
    expect(shouldSoftLogout("loading", "not_authenticated")).toBe(false);
    expect(shouldSoftLogout("anon", "not_authenticated")).toBe(false);
  });

  it.each(["REGWEB_EXPIRED", "SCO_EXPIRED"])(
    "also logs out on the per-family code %s (upstream jar death needs a full re-login)",
    (detail) => {
      expect(shouldSoftLogout("authed", detail)).toBe(true);
    },
  );

  it.each(["not_authenticated", "SELCRS_EXPIRED", "session_expired", ""])(
    "still logs out on a site-session 401 like %j",
    (detail) => {
      expect(shouldSoftLogout("authed", detail)).toBe(true);
    },
  );
});

describe("isFamilyExpiredDetail", () => {
  it("matches only the two per-family codes, case-sensitively", () => {
    expect(isFamilyExpiredDetail("REGWEB_EXPIRED")).toBe(true);
    expect(isFamilyExpiredDetail("SCO_EXPIRED")).toBe(true);
    expect(isFamilyExpiredDetail("not_authenticated")).toBe(false);
    expect(isFamilyExpiredDetail("regweb_expired")).toBe(false);
    expect(isFamilyExpiredDetail("REGWEB_EXPIRED ")).toBe(false);
  });
});

describe("shouldForceRelogin", () => {
  it("fires only for an authed zombie session while the feature is enabled", () => {
    expect(shouldForceRelogin("authed", true, false, true)).toBe(true);
    expect(shouldForceRelogin("authed", true, true, false)).toBe(true);
    expect(shouldForceRelogin("authed", true, false, false)).toBe(true);
    expect(shouldForceRelogin("authed", true, true, true)).toBe(false);
    expect(shouldForceRelogin("authed", false, false, false)).toBe(false);
    expect(shouldForceRelogin("anon", true, false, false)).toBe(false);
    expect(shouldForceRelogin("loading", true, false, false)).toBe(false);
  });
});

describe("loginNoticeText", () => {
  it("distinguishes expired from never-logged-in", () => {
    expect(loginNoticeText("expired")).toBe("登入階段已過期，請重新登入。");
    expect(loginNoticeText("required")).toBe("此頁面需要先登入。");
    expect(loginNoticeText(null)).toBeNull();
    expect(loginNoticeText("bogus")).toBeNull();
  });
});

describe("loginErrorText", () => {
  it("maps the school verdict taxonomy", () => {
    expect(loginErrorText(401, "invalid_credentials", null)).toBe("學號或密碼錯誤");
    expect(loginErrorText(503, "school_unavailable", null)).toBe(
      "學校系統異常，稍後再試",
    );
  });

  it("carries the retry window for locked accounts", () => {
    expect(loginErrorText(429, "too_many_attempts", 15)).toBe(
      "嘗試次數過多，帳號暫時鎖定，請約 15 分鐘後再試",
    );
    expect(loginErrorText(423, "too_many_attempts", 8)).toBe(
      "帳號已鎖定，請約 8 分鐘後再試",
    );
    expect(loginErrorText(429, "too_many_attempts", null)).toBe(
      "嘗試次數過多，請稍後再試",
    );
  });

  it("falls back for anything else", () => {
    expect(loginErrorText(400, "student_no_required", null)).toBe(
      "登入失敗，請稍後再試",
    );
  });
});
