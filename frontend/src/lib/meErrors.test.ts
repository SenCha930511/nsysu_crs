import { describe, expect, it } from "vitest";

import { ApiError } from "./api";
import { meFeatureErrorKind } from "./meErrors";

describe("meFeatureErrorKind", () => {
  it("maps school-side failures to school_unavailable", () => {
    expect(meFeatureErrorKind(new ApiError(503, "school_unavailable"))).toBe(
      "school_unavailable",
    );
    expect(meFeatureErrorKind(new ApiError(503, "breaker_open"))).toBe(
      "school_unavailable",
    );
    expect(meFeatureErrorKind(new ApiError(500, "school_unavailable"))).toBe(
      "school_unavailable",
    );
  });

  it.each(["REGWEB_EXPIRED", "SCO_EXPIRED"])(
    "keeps the per-family 401 %s in-page instead of logging out",
    (detail) => {
      expect(meFeatureErrorKind(new ApiError(401, detail))).toBe(
        "campus_connection_expired",
      );
    },
  );

  it("hands genuine session death over to the global soft-logout seam", () => {
    expect(meFeatureErrorKind(new ApiError(401, "not_authenticated"))).toBe(
      "session_dead",
    );
    expect(meFeatureErrorKind(new ApiError(401, "SELCRS_EXPIRED"))).toBe(
      "session_dead",
    );
  });

  it("treats 404 as feature-not-enabled (FEATURE_STU_ENROLL off)", () => {
    expect(meFeatureErrorKind(new ApiError(404, "not_found"))).toBe("feature_off");
  });

  it("falls back to generic for anything else", () => {
    expect(meFeatureErrorKind(new ApiError(500, "boom"))).toBe("generic");
    expect(meFeatureErrorKind(new TypeError("network down"))).toBe("generic");
    expect(meFeatureErrorKind("not-an-error")).toBe("generic");
  });
});
