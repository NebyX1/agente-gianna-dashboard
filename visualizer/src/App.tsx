import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient } from "./api/queryClient";
import {
  LoginPage,
  PasswordPage,
  SessionGate,
  VerificationPage,
} from "./components/Auth";
import { DisplayPage } from "./features/display/DisplayPage";
import { useAuth } from "./store/auth";
import "./styles/display.css";
export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/verificacion" element={<VerificationPage />} />
          <Route
            path="/pantalla"
            element={
              <SessionGate>
                <DisplayPage />
              </SessionGate>
            }
          />
          <Route
            path="/cuenta"
            element={
              <SessionGate>
                <main className="auth-simple">
                  <PasswordPage />
                </main>
              </SessionGate>
            }
          />
          <Route
            path="*"
            element={
              <Navigate
                to={useAuth.getState().token ? "/pantalla" : "/login"}
                replace
              />
            }
          />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
