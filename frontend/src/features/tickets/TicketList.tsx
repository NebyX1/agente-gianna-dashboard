import { Link } from "react-router-dom";
import { ArrowRight, ArrowUpRight } from "lucide-react";
import { age, formatDate } from "../../utils/time";
import type { Status, Ticket } from "../../types";

export function TicketList({
  tickets,
  label,
  onChange,
  busy,
}: {
  tickets: Ticket[];
  label: (status: Status) => string;
  onChange: (ticket: Ticket) => void;
  busy: boolean;
}) {
  return (
    <div className="ticket-list">
      <table className="table" aria-label="Lista de tickets">
        <thead>
          <tr>
            <th>Solicitud</th>
            <th>Origen y destino</th>
            <th>Estado</th>
            <th>Antigüedad</th>
            <th>
              <span className="sr-only">Acciones</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {tickets.map((ticket) => (
            <tr key={ticket.id} data-testid={`row-${ticket.code}`}>
              <td className="list-request">
                <Link to={`/tickets/${ticket.id}`} className="ticket-code">
                  {ticket.code}
                  <ArrowUpRight size={13} />
                </Link>
                <strong>{ticket.problem_type.name}</strong>
                <p title={ticket.description}>{ticket.description}</p>
              </td>
              <td>
                <div className="list-route">
                  <span>{ticket.origin.name}</span>
                  <ArrowRight size={13} />
                  <span>{ticket.destination.name}</span>
                </div>
              </td>
              <td>
                <span className={`state-badge state-badge-${ticket.status}`}>
                  {label(ticket.status)}
                </span>
              </td>
              <td>
                <time
                  dateTime={ticket.created_at}
                  title={formatDate(ticket.created_at)}
                >
                  Hace {age(ticket.created_at)}
                </time>
              </td>
              <td>
                <button
                  className="ticket-action"
                  disabled={busy}
                  onClick={() => onChange(ticket)}
                >
                  Cambiar estado
                  <ArrowRight size={13} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
