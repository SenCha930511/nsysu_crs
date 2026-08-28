/**
 * Routed app: the unified console at "/" (browse+selections+write), /login,
 * guarded /plans (multi-plan + 志願序), /write (送單紀錄) and the public
 * legal pages /privacy, /tos, /faq.
 * Provider nesting: Router > Auth > Selection > PlansSync - plans sync
 * consumes both the auth status (boot/reset seams) and the selection seam
 * (hydrate silently, write back on change).
 */

import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import AppShell from "./components/AppShell";
import { RequireAuth } from "./components/RequireAuth";
import FaqPage from "./pages/FaqPage";
import HomePage from "./pages/HomePage";
import LoginPage from "./pages/LoginPage";
import PlansPage from "./pages/PlansPage";
import PrivacyPage from "./pages/PrivacyPage";
import RecordsPage from "./pages/RecordsPage";
import TermsPage from "./pages/TermsPage";
import { AuthProvider } from "./state/auth";
import { PlansSyncProvider } from "./state/plansSync";
import { SelectionProvider } from "./state/selection";

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <SelectionProvider>
          <PlansSyncProvider>
            <Routes>
              <Route element={<AppShell />}>
                <Route index element={<HomePage />} />
                <Route path="login" element={<LoginPage />} />
                <Route path="privacy" element={<PrivacyPage />} />
                <Route path="tos" element={<TermsPage />} />
                <Route path="faq" element={<FaqPage />} />
                <Route
                  path="plans"
                  element={
                    <RequireAuth>
                      <PlansPage />
                    </RequireAuth>
                  }
                />
                <Route
                  path="write"
                  element={
                    <RequireAuth>
                      <RecordsPage />
                    </RequireAuth>
                  }
                />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Route>
            </Routes>
          </PlansSyncProvider>
        </SelectionProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
