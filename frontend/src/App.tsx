import { lazy } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient } from "./api/queryClient";
import {
  LoginPage,
  PasswordPage,
  SessionGate,
  VerificationPage,
} from "./components/Auth";
import { AppLayout } from "./components/AppLayout";
import { ThemeProvider } from "./components/ThemeProvider";
import { useAuth } from "./store/auth";
import "./styles/operational.css";
import { GiannaFormPage } from "./pages/Gianna";
const TicketsPage = lazy(() =>
  import("./pages/Tickets").then((module) => ({ default: module.TicketsPage })),
);
const DetailPage = lazy(() =>
  import("./pages/Detail").then((module) => ({ default: module.DetailPage })),
);
const StatisticsPage = lazy(() =>
  import("./pages/Statistics").then((module) => ({
    default: module.StatisticsPage,
  })),
);
const AdminPage = lazy(() =>
  import("./pages/Admin").then((module) => ({ default: module.AdminPage })),
);
export default function App() {
  return (
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/verificacion" element={<VerificationPage />} />
            <Route
              element={
                <SessionGate>
                  <AppLayout />
                </SessionGate>
              }
            >
              <Route path="/tickets" element={<TicketsPage />} />
              <Route path="/gianna/preview" element={<GiannaFormPage preview />} />
              <Route path="/gianna/manual" element={<GiannaFormPage preview={false} />} />
              <Route path="/tickets/:id" element={<DetailPage />} />
              <Route path="/estadisticas" element={<StatisticsPage />} />
              <Route path="/admin/:section?" element={<AdminPage />} />
              <Route path="/cuenta" element={<PasswordPage />} />
            </Route>
            <Route
              path="*"
              element={
                <Navigate
                  to={useAuth.getState().token ? "/tickets" : "/login"}
                  replace
                />
              }
            />
          </Routes>
        </BrowserRouter>
      </QueryClientProvider>
    </ThemeProvider>
  );
}
