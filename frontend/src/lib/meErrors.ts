/**
 * /me per-card fetch-error classification (pure; vitest in node env).
 * The page maps the returned kind to bilingual copy; a real session-death
 * 401 maps to "session_dead" and renders NOTHING locally because the global
 * soft-logout seam already redirects to /login?reason=expired.
 */

import { ApiError } from "./api";
import { isFamilyExpiredDetail } from "./guards";

export type MeFeatureErrorKind =
  | "school_unavailable"
  | "campus_connection_expired"
  | "feature_off"
  | "session_dead"
  | "generic";

export function meFeatureErrorKind(err: unknown): MeFeatureErrorKind {
  if (!(err instanceof ApiError)) return "generic";
  if (err.status === 503 || err.detail === "school_unavailable") {
    return "school_unavailable";
  }
  // Per-family 401: only that feature's school jar died; the site session is
  // alive, so this stays in-page (mirrors shouldSoftLogout's exemption).
  if (isFamilyExpiredDetail(err.detail)) return "campus_connection_expired";
  if (err.status === 401) return "session_dead";
  // FEATURE_STU_ENROLL off on the backend (or a flag race): same handling as
  // "not connected for this account", never an error.
  if (err.status === 404) return "feature_off";
  return "generic";
}
