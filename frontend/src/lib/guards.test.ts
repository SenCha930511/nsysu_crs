import { describe, expect, it } from "vitest";

import {
  decideGuard,
  shouldSoftLogout,
  loginErrorText,
  loginNoticeText,
} from "./guards";

describe("decideGuard", () => {
  it.each(["/plans", "/selected", "/write"])(
    "redirects anonymous visitors of %s to /login?reason=required",
    (path) => {
      expect(decideGuard("anon", path)).toEqual({
        allow: false,
        redirectTo: "/login?reason=required",
      });
    },
  );

  it("redirects to /login?reason=expired after a soft logout", () => {
    expect(decideGuard("anon", "/plans", true)).toEqual({
      allow: false,
      redirectTo: "/login?reason=expired",
    });
    expect(decideGuard("anon", "/selected", true).redirectTo).toBe(
      "/login?reason=expired",
    );
  });

  it("lets authed users into protected paths", () => {
    expect(decideGuard("authed", "/plans")).toEqual({
      allow: true,
      redirectTo: null,
    });
    expect(decideGuard("authed", "/selected")).toEqual({
      allow: true,
      redirectTo: null,
    });
  });

  it("holds (no redirect) while the session is still unknown", () => {
    expect(decideGuard("loading", "/plans")).toEqual({
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
    expect(shouldSoftLogout("authed")).toBe(true);
    expect(shouldSoftLogout("loading")).toBe(false);
    expect(shouldSoftLogout("anon")).toBe(false);
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
