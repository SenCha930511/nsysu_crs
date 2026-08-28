/**
 * Routed app: the unified console at "/" (browse+selections+write), /login,
 * guarded /write (送單紀錄) and the public legal pages /privacy, /tos, /faq.
 * Provider nesting: Router > Auth > Selection.
 */

import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import AppShell from "./components/AppShell";
import { RequireAuth } from "./components/RequireAuth";
import { I18nProvider } from "./lib/i18n";
import FaqPage from "./pages/FaqPage";
import HomePage from "./pages/HomePage";
import LoginPage from "./pages/LoginPage";
import PrivacyPage from "./pages/PrivacyPage";
import RecordsPage from "./pages/RecordsPage";
import TermsPage from "./pages/TermsPage";
import { AuthProvider } from "./state/auth";
import { SelectionProvider } from "./state/selection";

function App() {
  return (
    <I18nProvider>
      <BrowserRouter>
        <AuthProvider>
          <SelectionProvider>
            <Routes>
              <Route element={<AppShell />}>
                <Route index element={<HomePage />} />
                <Route path="login" element={<LoginPage />} />
                <Route path="privacy" element={<PrivacyPage />} />
                <Route path="tos" element={<TermsPage />} />
                <Route path="faq" element={<FaqPage />} />
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
          </SelectionProvider>
        </AuthProvider>
      </BrowserRouter>
    </I18nProvider>
  );
}

export default App;
