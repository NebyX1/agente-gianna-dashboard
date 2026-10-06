import { Link } from "react-router-dom";
import {
  ArrowUpRight,
  ArrowRight,
  Clock3,
  Monitor,
  Printer,
  Wifi,
  CircleHelp,
  Wrench,
} from "lucide-react";
import { age, formatDate } from "../../utils/time";
import type { Ticket } from "../../types";

export function TicketCard({
  ticket,
  label,
  onChange,
  preview = false,
  busy = false,
}: {
  ticket: Ticket;
  label: string;
  onChange?: () => void;
  preview?: boolean;
  busy?: boolean;
}) {
  const Icon =
    (
      {
        IMPRESORA: Printer,
        INTERNET: Wifi,
        HARDWARE: Wrench,
        SISTEMAS: Monitor,
      } as Record<string, typeof Monitor>
    )[ticket.problem_type.code] ?? CircleHelp;
  return (
    <article
      className={`ticket-card ticket-status-${ticket.status}${preview ? " ticket-card-preview" : ""}`}
      data-testid={preview ? "drag-preview" : `card-${ticket.code}`}
    >
      <div className="ticket-card-top">
        {preview ? (
          <span className="ticket-code">{ticket.code}</span>
        ) : (
          <Link className="ticket-code" to={`/tickets/${ticket.id}`}>
            {ticket.code}
            <ArrowUpRight size={13} />
          </Link>
        )}
        <span className={`state-badge state-badge-${ticket.status}`}>
          {label}
        </span>
      </div>
      <div className="ticket-title">
        <span className="problem-icon">
          <Icon size={17} />
        </span>
        <h3>{ticket.problem_type.name}</h3>
      </div>
      <p className="ticket-description">{ticket.description}</p>
      <div className="ticket-route">
        <span title={ticket.origin.name}>{ticket.origin.name}</span>
        <ArrowRight size={13} />
        <span title={ticket.destination.name}>{ticket.destination.name}</span>
      </div>
      <div className="ticket-bottom">
        <time
          dateTime={ticket.created_at}
          title={formatDate(ticket.created_at)}
        >
          <Clock3 size={13} />
          Hace {age(ticket.created_at)}
        </time>
        {!preview && (
          <button
            className="ticket-action"
            onClick={onChange}
            disabled={busy}
            aria-label="Cambiar estado"
          >
            Cambiar estado
            <ArrowRight size={12} />
          </button>
        )}
      </div>
    </article>
  );
}
