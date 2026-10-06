import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { Suspense } from "react";
import {
  LayoutDashboard,
  ChartNoAxesCombined,
  Settings2,
  LogOut,
  Moon,
  Sun,
  KeyRound,
  ChevronRight,
} from "lucide-react";
import { logout } from "./Auth";
import { Feedback, useFeedback } from "./Feedback";
import { useTheme } from "./ThemeProvider";
import { useAuth } from "../store/auth";
import { errorMessage } from "../api/axios";

export function AppLayout() {
  const user = useAuth((state) => state.user);
  const { theme, toggle } = useTheme();
  const { pathname } = useLocation();
  const section = pathname.startsWith("/admin")
    ? "Administración"
    : pathname.startsWith("/estadisticas")
      ? "Estadísticas"
      : pathname.startsWith("/cuenta")
        ? "Mi cuenta"
        : "Solicitudes";
  return (
    <div className="app-layout">
      <aside className="sidebar">
        <Link to="/tickets" className="sidebar-brand">
          <img src="/Logo.webp" alt="Escudo de Lavalleja" />
          <span>
            <strong>Lavalleja</strong>
            <small>Mesa de ayuda</small>
          </span>
        </Link>
        <div className="sidebar-caption">ESPACIO DE TRABAJO</div>
        <nav aria-label="Navegación principal">
          <NavLink to="/tickets">
            <LayoutDashboard size={19} />
            Solicitudes
          </NavLink>
          <NavLink to="/estadisticas">
            <ChartNoAxesCombined size={19} />
            Estadísticas
          </NavLink>
          {user?.role === "admin" && (
            <NavLink to="/admin">
              <Settings2 size={19} />
              Administración
            </NavLink>
          )}
        </nav>
        <div className="sidebar-bottom">
          <Link className="account-link" to="/cuenta">
            <KeyRound size={17} />
            Mi cuenta
          </Link>
          <div className="user-block">
            <span className="user-avatar" aria-hidden="true">
              {user?.name.slice(0, 1).toUpperCase()}
            </span>
            <div>
              <strong>{user?.name}</strong>
              <small>
                {user?.role === "admin" ? "Administrador" : "Operador"}
              </small>
            </div>
            <button
              className="icon-button"
              aria-label="Cerrar sesión"
              title="Cerrar sesión"
              onClick={async () => {
                try {
                  await logout();
                } catch (error) {
                  useFeedback.getState().show(errorMessage(error), true);
                }
              }}
            >
              <LogOut size={17} />
            </button>
          </div>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div className="breadcrumbs">
            <span>Mesa de ayuda</span>
            <ChevronRight size={14} />
            <strong>{section}</strong>
          </div>
          <button
            className="theme-toggle"
            aria-label="Modo nocturno"
            aria-pressed={theme === "dark"}
            title={
              theme === "dark" ? "Activar modo claro" : "Activar modo nocturno"
            }
            onClick={toggle}
          >
            {theme === "dark" ? <Moon size={17} /> : <Sun size={17} />}
            <span>{theme === "dark" ? "Modo nocturno" : "Modo claro"}</span>
            <span className="theme-switch" aria-hidden="true" />
          </button>
        </header>
        <main className="main-content">
          <Suspense
            fallback={
              <div className="board-loading" role="status">
                Cargando vista…
              </div>
            }
          >
            <Outlet />
          </Suspense>
        </main>
      </div>
      <Feedback />
    </div>
  );
}
