import { useEffect, useState, type ReactNode } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api, clearSession, errorMessage, get, post } from "../api/axios";
import { useAuth } from "../store/auth";
import { env } from "../config/env";
import type { Envelope, User } from "../types";
export function SessionGate({ children }: { children: ReactNode }) {
  const { token, expiresAt, user } = useAuth();
  const query = useQuery({
    queryKey: ["session", token],
    queryFn: () => get<User>("/auth/me"),
    enabled: !!token,
    staleTime: 60000,
    refetchInterval: 60000,
  });
  useEffect(() => {
    if (!token || !expiresAt) return;
    const remaining = Date.parse(expiresAt) - Date.now();
    if (remaining <= 0) {
      clearSession("La sesión venció. Iniciá sesión nuevamente.");
      return;
    }
    const timer = setTimeout(
      () => clearSession("La sesión venció. Iniciá sesión nuevamente."),
      remaining,
    );
    return () => clearTimeout(timer);
  }, [token, expiresAt]);
  if (!token) return <Navigate to="/login" replace />;
  if (query.isPending)
    return (
      <div className="empty" role="status">
        Validando sesión…
      </div>
    );
  if (query.isError && !query.data)
    return (
      <div className="empty" role="alert">
        <h1>No se pudo validar la sesión</h1>
        <p>{errorMessage(query.error)}</p>
        <button
          className="btn btn-primary"
          onClick={() => void query.refetch()}
        >
          Reintentar
        </button>
      </div>
    );
  if (!env.display && (query.data?.role ?? user?.role) === "viewer")
    return (
      <div className="empty" role="alert">
        <h1>Cuenta de visualización</h1>
        <p>
          Usá esta cuenta en la aplicación de pantalla. El sistema operativo
          requiere rol operador o administrador.
        </p>
        <button className="btn" onClick={() => void logout()}>
          Salir
        </button>
      </div>
    );
  return children;
}
export async function logout() {
  try {
    await post("/auth/logout", {});
    clearSession();
  } catch (error) {
    throw new Error(errorMessage(error), { cause: error });
  }
}
export function LoginPage() {
  const navigate = useNavigate();
  const { setPending, reason } = useAuth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return (
    <main className="auth-shell">
      <section className="auth-intro">
        <img
          className="auth-logo"
          src="/Logo.webp"
          alt="Escudo de la Intendencia de Lavalleja"
        />
        <span className="institution">INTENDENCIA DE LAVALLEJA</span>
        <h1>{env.appName}</h1>
      </section>
      <section className="auth-form">
        <h2>Acceso al sistema</h2>
        <p>
          Ingresá con tu cuenta institucional.
          <br />
          Enviaremos un código de verificación a tu correo.
        </p>
        {reason && (
          <p role="alert" className="notice">
            {reason}
          </p>
        )}
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            if (busy) return;
            const data = new FormData(e.currentTarget);
            setBusy(true);
            setError("");
            try {
              const response = await post<{ pending_token: string }>(
                "/auth/login",
                { email: data.get("email"), password: data.get("password") },
              );
              setPending(response.pending_token);
              navigate("/verificacion");
            } catch (err) {
              setError(errorMessage(err));
            } finally {
              setBusy(false);
            }
          }}
        >
          <label htmlFor="email">Correo electrónico</label>
          <input
            id="email"
            name="email"
            type="email"
            className="input"
            autoComplete="username"
            required
            autoFocus
            data-testid="login-email"
          />
          <label htmlFor="password">Contraseña</label>
          <input
            id="password"
            name="password"
            type="password"
            className="input"
            autoComplete="current-password"
            required
            maxLength={256}
            data-testid="login-password"
          />
          {error && (
            <p role="alert" className="form-error">
              {error}
            </p>
          )}
          <button
            className="btn btn-primary"
            disabled={busy}
            data-testid="login-submit"
          >
            {busy ? "Enviando código…" : "Continuar →"}
          </button>
        </form>
        <small>Acceso protegido con verificación por correo.</small>
      </section>
    </main>
  );
}
export function VerificationPage() {
  const { pending, setPending, login, token } = useAuth();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [cooldown, setCooldown] = useState(60);
  useEffect(() => {
    const timer = setInterval(
      () => setCooldown((value) => Math.max(0, value - 1)),
      1000,
    );
    return () => clearInterval(timer);
  }, []);
  if (!pending)
    return (
      <Navigate
        to={token ? (env.display ? "/pantalla" : "/tickets") : "/login"}
        replace
      />
    );
  return (
    <main className="auth-simple">
      <section className="card auth-card">
        <span className="institution">INTENDENCIA DE LAVALLEJA</span>
        <h1>Revisá tu correo</h1>
        <p>
          Ingresá el código de seis dígitos. Vence en 10 minutos y sólo puede
          utilizarse una vez.
        </p>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            if (busy) return;
            const data = new FormData(e.currentTarget);
            setBusy(true);
            try {
              const result = await post<{
                access_token: string;
                user: User;
                expires_at: string;
              }>("/auth/verify-2fa", {
                pending_token: pending,
                code: data.get("code"),
              });
              login(result.access_token, result.user, result.expires_at);
              navigate(env.display ? "/pantalla" : "/tickets");
            } catch (err) {
              setMessage(errorMessage(err));
            } finally {
              setBusy(false);
            }
          }}
        >
          <label htmlFor="code">Código de verificación</label>
          <input
            id="code"
            name="code"
            className="input otp"
            inputMode="numeric"
            pattern="[0-9]{6}"
            maxLength={6}
            autoComplete="one-time-code"
            required
            autoFocus
            data-testid="otp-code"
          />
          <button className="btn btn-primary" disabled={busy}>
            Verificar e ingresar
          </button>
        </form>
        {message && <p role="alert">{message}</p>}
        <button
          className="btn btn-ghost"
          disabled={busy || cooldown > 0}
          onClick={async () => {
            setBusy(true);
            try {
              const result = await post<{ pending_token: string }>(
                "/auth/resend-2fa",
                { pending_token: pending },
              );
              setPending(result.pending_token);
              setCooldown(60);
              setMessage(
                "Enviamos un nuevo código; el anterior dejó de ser válido.",
              );
            } catch (err) {
              setMessage(errorMessage(err));
            } finally {
              setBusy(false);
            }
          }}
        >
          Reenviar código {cooldown > 0 ? `(${cooldown}s)` : ""}
        </button>
        <button
          className="btn btn-ghost"
          onClick={() => {
            setPending(null);
            navigate("/login");
          }}
        >
          Volver al inicio
        </button>
      </section>
    </main>
  );
}
export function PasswordPage() {
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <section className="panel max-w-xl">
      <h1>Cambiar contraseña</h1>
      <p>
        El cambio cierra todas tus sesiones. Volvé a iniciar sesión en cada
        aplicación.
      </p>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          const form = new FormData(e.currentTarget);
          setBusy(true);
          try {
            await api.put<Envelope<unknown>>("/auth/change-password", {
              current_password: form.get("current_password"),
              new_password: form.get("new_password"),
            });
            clearSession("Contraseña cambiada. Iniciá sesión nuevamente.");
          } catch (err) {
            setMessage(errorMessage(err));
          } finally {
            setBusy(false);
          }
        }}
      >
        <label htmlFor="current">Contraseña actual</label>
        <input
          className="input"
          id="current"
          name="current_password"
          type="password"
          autoComplete="current-password"
          required
        />
        <label htmlFor="new">Nueva contraseña (al menos 12 caracteres)</label>
        <input
          className="input"
          id="new"
          name="new_password"
          type="password"
          minLength={12}
          maxLength={256}
          autoComplete="new-password"
          required
        />
        {message && <p role="alert">{message}</p>}
        <button className="btn btn-primary" disabled={busy}>
          Cambiar contraseña
        </button>
      </form>
    </section>
  );
}
