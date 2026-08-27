/** Route guard: protected paths bounce anonymous visitors to /login. */

import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { decideGuard } from "../lib/guards";
import { useAuth } from "../state/auth";

export function RequireAuth({ children }: { children: ReactNode }) {
  const { status, expired } = useAuth();
  const location = useLocation();
  const decision = decideGuard(status, location.pathname, expired);

  if (decision.allow) return children;
  if (decision.redirectTo !== null) {
    return (
      <Navigate
        to={decision.redirectTo}
        state={{ from: location.pathname }}
        replace
      />
    );
  }
  return (
    <div className="text-center text-muted py-5" role="status">
      讀取登入狀態中…
    </div>
  );
}
