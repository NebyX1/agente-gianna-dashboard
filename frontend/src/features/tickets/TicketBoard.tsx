import { Inbox, Plus } from "lucide-react";
import { Draggable, Droppable } from "../../components/Drag";
import { TicketCard } from "./TicketCard";
import type { StatusDefinition, Ticket } from "../../types";

export function TicketBoard({
  tickets,
  statuses,
  activeOnly,
  busy,
  onCreate,
  onChange,
}: {
  tickets: Ticket[];
  statuses: StatusDefinition[];
  activeOnly: boolean;
  busy: boolean;
  onCreate: () => void;
  onChange: (ticket: Ticket) => void;
}) {
  const columns = statuses.filter(
    (status) =>
      !activeOnly || ["new", "in_progress", "waiting"].includes(status.code),
  );
  return (
    <div
      className="kanban"
      style={{
        gridTemplateColumns: `repeat(${columns.length}, minmax(280px, 1fr))`,
      }}
      aria-label="Tablero de tickets"
    >
      {columns.map((status) => {
        const items = tickets.filter((ticket) => ticket.status === status.code);
        return (
          <Droppable
            key={status.code}
            id={`column-${status.code}`}
            className={`kanban-column column-${status.code}`}
          >
            <div className="column-heading">
              <h2>
                <span className="column-dot" />
                {status.label}
                <span className="column-count">{items.length}</span>
              </h2>
              {status.code === "new" && (
                <button
                  className="icon-button"
                  aria-label="Crear ticket en Nuevo"
                  onClick={onCreate}
                >
                  <Plus size={17} />
                </button>
              )}
            </div>
            <div className="column-content">
              {items.map((ticket) => (
                <Draggable
                  id={`ticket-${ticket.id}`}
                  label={`Arrastrar ticket ${ticket.code}`}
                  key={ticket.id}
                  wholeCard
                  disabled={busy}
                >
                  <TicketCard
                    ticket={ticket}
                    label={status.label}
                    onChange={() => onChange(ticket)}
                    busy={busy}
                  />
                </Draggable>
              ))}
              {items.length === 0 && (
                <div className="column-empty">
                  <Inbox size={24} strokeWidth={1.3} />
                  <span>Sin tickets</span>
                </div>
              )}
            </div>
          </Droppable>
        );
      })}
    </div>
  );
}
