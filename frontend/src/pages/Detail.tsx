import { useRef, useState } from "react";
import axios from "axios";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { errorMessage, get, post } from "../api/axios";
import { refreshTickets, useCatalogs } from "../api/hooks/useTickets";
import { TicketForm } from "../components/TicketForm";
import { StatusChange } from "../components/StatusChange";
import { Modal } from "../components/Modal";
import { useFeedback } from "../components/Feedback";
import { useAuth } from "../store/auth";
import { formatDate } from "../utils/time";
import type { Page, Ticket, TicketEvent } from "../types";
export function DetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const catalogs = useCatalogs();
  const [historyPage, setHistoryPage] = useState(1);
  const [action, setAction] = useState<
    "edit" | "status" | "archive" | "restore" | null
  >(null);
  const query = useQuery({
    queryKey: ["ticket", id],
    queryFn: () => get<Ticket>(`/tickets/${id}`),
    refetchInterval: action ? false : 5000,
    refetchOnWindowFocus: !action,
    refetchOnReconnect: !action,
  });
  const history = useQuery({
    queryKey: ["history", id, historyPage],
    queryFn: () =>
      get<Page<TicketEvent>>(`/tickets/${id}/history`, { page: historyPage }),
    enabled: query.isSuccess,
  });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const key = useRef(crypto.randomUUID());
  const archiveAttempt = useRef<{ version: number; reason: string } | null>(
    null,
  );
  const role = useAuth((s) => s.user?.role);
  if (query.isPending) return <p role="status">Cargando detalle…</p>;
  if (query.isError)
    return (
      <div role="alert" className="empty">
        <p>{errorMessage(query.error)}</p>
        <button className="btn" onClick={() => void query.refetch()}>
          Recargar
        </button>
      </div>
    );
  const ticket = query.data;
  const label =
    catalogs.data?.statuses.find((s) => s.code === ticket.status)?.label ??
    ticket.status;
  const eventLabels: Record<string, string> = {
    created: "Ticket registrado",
    edited: "Datos editados",
    status_changed: "Cambio de estado",
    reopened: "Ticket reabierto",
    archived: "Ticket ocultado",
    restored: "Ticket restaurado",
  };
  return (
    <section data-testid="ticket-detail" data-ticket-id={ticket.id} data-ticket-code={ticket.code}>
      <Link to="/tickets" className="back-link">
        ← Volver a solicitudes
      </Link>
      <div className="page-heading">
        <div>
          <span className="eyebrow">DETALLE DE SOLICITUD</span>
          <h1>{ticket.code}</h1>
          <p className="muted">
            Registrado el {formatDate(ticket.created_at)} · Versión{" "}
            {ticket.version}
          </p>
        </div>
        <span className={`state-badge state-badge-${ticket.status}`}>
          {label}
        </span>
      </div>
      {ticket.archived_at && (
        <p className="notice">
          Ticket oculto desde {formatDate(ticket.archived_at)}. Motivo:{" "}
          {ticket.archive_reason}. Restauralo para modificarlo.
        </p>
      )}
      <div className="detail-layout">
        <section className="panel">
          <dl className="ticket-facts">
            <div>
              <dt>Origen</dt>
              <dd>{ticket.origin.name}</dd>
            </div>
            <div>
              <dt>Destino responsable</dt>
              <dd>{ticket.destination.name}</dd>
            </div>
            <div>
              <dt>Tipo de problema</dt>
              <dd>{ticket.problem_type.name}</dd>
            </div>
            {ticket.occurred_at && (
              <div>
                <dt>Inicio del problema</dt>
                <dd>{formatDate(ticket.occurred_at)}</dd>
              </div>
            )}
          </dl>
          <h2>Descripción</h2>
          <p className="full-description">{ticket.description}</p>
          <div className="actions">
            {!ticket.archived_at ? (
              <>
                <button
                  className="btn btn-primary"
                  onClick={() => setAction("status")}
                >
                  Cambiar estado
                </button>
                <button className="btn" onClick={() => setAction("edit")}>
                  Editar ticket
                </button>
                <button
                  className="btn btn-ghost"
                  onClick={() => {
                    archiveAttempt.current = null;
                    key.current = crypto.randomUUID();
                    setMessage("");
                    setAction("archive");
                  }}
                >
                  Ocultar ticket
                </button>
              </>
            ) : (
              role === "admin" && (
                <button
                  className="btn btn-primary"
                  onClick={() => setAction("restore")}
                >
                  Restaurar ticket
                </button>
              )
            )}
          </div>
        </section>
        <section className="panel">
          <h2>Historial</h2>
          {history.isPending && <p>Cargando historial…</p>}
          {history.isError && <p role="alert">{errorMessage(history.error)}</p>}
          <ol className="history">
            {history.data?.items.map((event) => (
              <li key={event.id}>
                <strong>
                  {eventLabels[event.event_type] ?? event.event_type}
                </strong>
                <p>
                  {event.actor_name} · {formatDate(event.timestamp)}
                </p>
                {event.note && <p className="history-note">{event.note}</p>}
                <details>
                  <summary>Ver cambios y trazabilidad</summary>
                  <p>
                    Canal: {event.channel} · Solicitud: {event.request_id}
                  </p>
                  {event.before && (
                    <pre>{JSON.stringify(event.before, null, 2)}</pre>
                  )}
                  <pre>{JSON.stringify(event.after, null, 2)}</pre>
                </details>
              </li>
            ))}
          </ol>
          {history.data && history.data.pages > 1 && (
            <div className="pagination">
              <button
                className="btn"
                disabled={historyPage === 1}
                onClick={() => setHistoryPage((p) => p - 1)}
              >
                Anterior
              </button>
              <span>
                {historyPage} / {history.data.pages}
              </span>
              <button
                className="btn"
                disabled={historyPage >= history.data.pages}
                onClick={() => setHistoryPage((p) => p + 1)}
              >
                Siguiente
              </button>
            </div>
          )}
        </section>
      </div>
      {action === "edit" && catalogs.data && (
        <TicketForm
          initial={ticket}
          catalogs={catalogs.data}
          onClose={() => setAction(null)}
        />
      )}
      {action === "status" && catalogs.data && (
        <StatusChange
          ticket={ticket}
          statuses={catalogs.data.statuses}
          onClose={() => setAction(null)}
        />
      )}
      {(action === "archive" || action === "restore") && (
        <Modal
          title={action === "archive" ? "Ocultar ticket" : "Restaurar ticket"}
          onClose={() => {
            if (busy || archiveAttempt.current) {
              setMessage(
                "Confirmá el resultado del intento pendiente antes de cerrar.",
              );
              return;
            }
            setAction(null);
          }}
        >
          <p>
            {action === "archive"
              ? "El ticket desaparecerá del tablero y la pantalla para todos. Se conserva su historial y un administrador podrá restaurarlo."
              : "El ticket vuelve a estar visible, conservando su estado actual."}
          </p>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              if (busy) return;
              const data = new FormData(e.currentTarget);
              const body = {
                version: ticket.version,
                reason: String(data.get("reason")).trim(),
              };
              setBusy(true);
              setMessage("");
              try {
                if (action === "archive") {
                  archiveAttempt.current ??= body;
                  await post(
                    `/tickets/${ticket.id}/archive`,
                    archiveAttempt.current,
                    key.current,
                  );
                } else await post(`/admin/tickets/${ticket.id}/restore`, body);
                archiveAttempt.current = null;
                await refreshTickets();
                useFeedback
                  .getState()
                  .show(
                    action === "archive"
                      ? "Ticket ocultado; historial conservado"
                      : "Ticket restaurado",
                  );
                setAction(null);
                if (action === "archive") navigate("/tickets");
              } catch (err) {
                const status = axios.isAxiosError(err)
                  ? err.response?.status
                  : undefined;
                const uncertain =
                  action === "archive" && (!status || status >= 500);
                if (!uncertain) archiveAttempt.current = null;
                setMessage(
                  errorMessage(err) +
                    (uncertain
                      ? " Reintentá el mismo intento para confirmar el resultado de la ocultación."
                      : status === 409
                        ? " Cerrá este diálogo y recargá el detalle antes de volver a intentar."
                        : ""),
                );
              } finally {
                setBusy(false);
              }
            }}
          >
            <label htmlFor="archive-reason">Motivo</label>
            <textarea
              className="textarea"
              id="archive-reason"
              name="reason"
              required
              minLength={3}
              maxLength={1000}
              readOnly={!!archiveAttempt.current}
            />
            {message && <p role="alert">{message}</p>}
            <button className="btn btn-primary" disabled={busy}>
              Confirmar {action === "archive" ? "ocultación" : "restauración"}
            </button>
          </form>
        </Modal>
      )}
    </section>
  );
}
