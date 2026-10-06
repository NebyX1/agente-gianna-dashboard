import { useEffect, useState } from "react";
import { Maximize, Minimize, LogOut, RefreshCw } from "lucide-react";
import { useDisplayConfig, useTickets } from "../../hooks/useTickets";
import {
  connectionState,
  useNow,
  useOnline,
} from "../../hooks/useConnectionState";
import { capacity, pageItems } from "../../utils/rotation";
import { latestTicket } from "../../utils/featured";
import { age, formatDate } from "../../utils/time";
import { env } from "../../config/env";
import { errorMessage } from "../../api/axios";
import { logout } from "../../components/Auth";
import type { Status } from "../../types";
export function DisplayPage() {
  const [destination, setDestination] = useState("");
  const query = useTickets(destination);
  const config = useDisplayConfig();
  const now = useNow();
  const online = useOnline();
  const [page, setPage] = useState(0);
  const [size, setSize] = useState(() => capacity(innerWidth, innerHeight));
  const [fullscreen, setFullscreen] = useState(!!document.fullscreenElement);
  const [message, setMessage] = useState("");
  useEffect(() => {
    const resize = () => setSize(capacity(innerWidth, innerHeight));
    const fullscreen = () => setFullscreen(!!document.fullscreenElement);
    window.addEventListener("resize", resize);
    document.addEventListener("fullscreenchange", fullscreen);
    return () => {
      window.removeEventListener("resize", resize);
      document.removeEventListener("fullscreenchange", fullscreen);
    };
  }, []);
  const totalPages = Math.max(
    1,
    Math.ceil((query.data?.items.length ?? 0) / size.size),
  );
  useEffect(() => {
    const timer = setInterval(
      () => setPage((p) => (p + 1) % totalPages),
      env.pageMs,
    );
    return () => clearInterval(timer);
  }, [totalPages]);
  const state = connectionState(
    !!query.data,
    query.isError,
    query.dataUpdatedAt,
    now,
    online,
  );
  const rotation = pageItems(query.data?.items ?? [], page, size.size);
  const featured = latestTicket(query.data?.items ?? []);
  const labels = (status: Status) =>
    config.data?.statuses.find((s) => s.code === status)?.label ??
    {
      new: "Nuevo",
      in_progress: "En curso",
      waiting: "En espera",
      resolved: "Resuelto",
      cancelled: "Cancelado",
    }[status];
  const counts = (["new", "in_progress", "waiting"] as const).map((s) => ({
    code: s,
    count: query.data?.items.filter((t) => t.status === s).length ?? 0,
  }));
  return (
    <main className="display-screen">
      <header className="display-header">
        <div className="display-brand">
          <img src="/Logo.webp" alt="Escudo de la Intendencia de Lavalleja" />
          <div>
            <span className="display-institution">
              Intendencia de Lavalleja
            </span>
            <h1>{env.appName}</h1>
          </div>
        </div>
        <div className="display-clock">
          <strong>
            {new Intl.DateTimeFormat("es-UY", {
              timeZone: env.timezone,
              hour: "2-digit",
              minute: "2-digit",
              second: "2-digit",
              hourCycle: "h23",
            }).format(now)}
          </strong>
          <span>Mesa de ayuda · Seguimiento en vivo</span>
        </div>
      </header>
      <div className="display-date-row">
        {new Intl.DateTimeFormat("es-UY", {
          timeZone: env.timezone,
          weekday: "long",
          day: "numeric",
          month: "long",
          year: "numeric",
        }).format(now)}
      </div>
      {featured && (
        <section
          className="display-featured"
          aria-label="Ticket con la actualización más reciente"
          key={`${featured.id}:${featured.updated_at}`}
        >
          <div className="display-featured-label">
            Última actualización · {labels(featured.status)}
          </div>
          <strong className="display-featured-code">{featured.code}</strong>
          <h2 title={featured.problem_type.name}>
            {featured.problem_type.name}
          </h2>
          <p className="display-featured-route">
            {featured.origin.name} → {featured.destination.name}
          </p>
        </section>
      )}
      <section
        className="display-summary"
        aria-label="Resumen de tickets activos"
      >
        <div className="total-active">
          <h2>Tickets activos</h2>
          <span>
            {query.data?.total ?? "—"} en seguimiento
            {destination ? " del destino" : ""}
          </span>
        </div>
        <div className="display-counts">
          {counts.map((s) => (
            <div key={s.code}>
              <span className={`state-badge state-badge-${s.code}`}>
                {labels(s.code)}
              </span>
              <strong>{query.data ? s.count : "—"}</strong>
            </div>
          ))}
        </div>
        <div className="display-filter">
          <label htmlFor="destination-filter">Destino</label>
          <select
            id="destination-filter"
            className="select"
            value={destination}
            onChange={(e) => {
              setDestination(e.target.value);
              setPage(0);
            }}
          >
            <option value="">Todos los destinos</option>
            {config.data?.destinations.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </div>
      </section>
      {destination && (
        <p className="filter-notice">
          Filtro activo:{" "}
          {config.data?.destinations.find((d) => String(d.id) === destination)
            ?.name ?? destination}
          . Se muestra sólo este destino.
        </p>
      )}
      <div
        className={`connection-banner connection-${state}`}
        role={state === "stale" || state === "error" ? "alert" : "status"}
      >
        {state === "current"
          ? "● Actualizado"
          : state === "loading"
            ? "Cargando solicitudes…"
            : state === "stale"
              ? "Datos desactualizados · Conservamos la última información recibida"
              : "No se pudo obtener la información. Revisá la conexión."}
        {query.dataUpdatedAt > 0 && (
          <span>
            Última sincronización:{" "}
            {formatDate(new Date(query.dataUpdatedAt).toISOString())}
          </span>
        )}
        {(state === "stale" || state === "error") && (
          <button className="btn btn-sm" onClick={() => void query.refetch()}>
            <RefreshCw size={16} />
            Reintentar
          </button>
        )}
      </div>
      {state === "loading" && (
        <div className="display-empty">
          <div className="loading loading-spinner" />
          <h2>Cargando tickets activos</h2>
        </div>
      )}
      {state === "error" && (
        <div className="display-empty">
          <h2>Información no disponible</h2>
          <p>{errorMessage(query.error)}</p>
          <button
            className="btn btn-primary"
            onClick={() => void query.refetch()}
          >
            Volver a consultar
          </button>
        </div>
      )}
      {query.data && query.data.total === 0 && (
        <div className="display-empty">
          <span className="empty-symbol">✓</span>
          <h2>
            No hay tickets activos{destination ? " para este destino" : ""}
          </h2>
          <p>
            {state === "current"
              ? "Las solicitudes nuevas aparecerán automáticamente."
              : "El último conjunto recibido estaba vacío; aguardando conexión para confirmar."}
          </p>
        </div>
      )}
      {query.data && query.data.total > 0 && (
        <section
          className="display-grid"
          style={{
            gridTemplateColumns: `repeat(${size.columns}, minmax(0, 1fr))`,
            gridTemplateRows: `repeat(${size.rows}, minmax(0, var(--display-card-height)))`,
          }}
          aria-label="Tickets de la página"
        >
          {rotation.items.map((ticket) => (
            <article
              className={`display-ticket display-ticket-${ticket.status}${ticket.id === featured?.id ? " display-ticket-featured" : ""}`}
              key={ticket.id}
              data-testid="display-ticket"
            >
              <div className="display-ticket-top">
                <strong>{ticket.code}</strong>
                <span className={`state-badge state-badge-${ticket.status}`}>
                  {labels(ticket.status)}
                </span>
              </div>
              <h2 title={ticket.problem_type.name}>
                {ticket.problem_type.name}
              </h2>
              <div className="display-route">
                <span title={ticket.origin.name}>{ticket.origin.name}</span>
                <span aria-label="hacia">→</span>
                <span title={ticket.destination.name}>
                  {ticket.destination.name}
                </span>
              </div>
              <p className="display-description">
                {ticket.description_preview}
                {ticket.description_preview.length === 400 ? "…" : ""}
              </p>
              <div className="display-ticket-bottom">
                <time dateTime={ticket.created_at}>
                  {formatDate(ticket.created_at)}
                </time>
                <span>Hace {age(ticket.created_at, now)}</span>
              </div>
            </article>
          ))}
        </section>
      )}
      <footer className="display-footer">
        <div>
          <strong>
            Página {rotation.page + 1} de {rotation.pages}
          </strong>
        </div>
        <div className="display-controls">
          <button
            className="btn btn-ghost"
            onClick={async () => {
              try {
                if (document.fullscreenElement) await document.exitFullscreen();
                else if (document.documentElement.requestFullscreen)
                  await document.documentElement.requestFullscreen();
                else setMessage("Este navegador no admite pantalla completa.");
              } catch {
                setMessage(
                  "No se pudo abrir pantalla completa. Usá la opción del navegador.",
                );
              }
            }}
          >
            {fullscreen ? <Minimize size={20} /> : <Maximize size={20} />}
            {fullscreen ? "Salir de pantalla completa" : "Pantalla completa"}
          </button>
          <button
            className="btn btn-ghost"
            onClick={async () => {
              try {
                await logout();
              } catch (error) {
                setMessage(errorMessage(error));
              }
            }}
          >
            <LogOut size={18} />
            Salir
          </button>
        </div>
      </footer>
      {message && (
        <p className="notice" role="alert">
          {message}
        </p>
      )}
      {config.isError && (
        <p className="notice" role="alert">
          No se pudo actualizar la configuración de pantalla.{" "}
          {errorMessage(config.error)}
        </p>
      )}
    </main>
  );
}
