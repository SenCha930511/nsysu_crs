/**
 * Routed app (todo 11/16/17): the todo-10 read-only core at "/", plus /login,
 * guarded /plans (multi-plan + 志願序), /selected (real selections),
 * /write (送單中心) and the public legal pages /privacy, /tos, /faq.
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
import SelectedPage from "./pages/SelectedPage";
import TermsPage from "./pages/TermsPage";
import WritePage from "./pages/WritePage";
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
                  path="selected"
                  element={
                    <RequireAuth>
                      <SelectedPage />
                    </RequireAuth>
                  }
                />
                <Route
                  path="write"
                  element={
                    <RequireAuth>
                      <WritePage />
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
