import { useState } from "react";
import { Modal } from "./Modal";
import { useStatusChange } from "../api/hooks/useTickets";
import type { Status, StatusDefinition, Ticket } from "../types";
export function StatusChange({
  ticket,
  statuses,
  target,
  onClose,
}: {
  ticket: Ticket;
  statuses: StatusDefinition[];
  target?: Status;
  onClose: () => void;
}) {
  const transitions =
    statuses.find((s) => s.code === ticket.status)?.transitions ?? [];
  const [status, setStatus] = useState<Status>(
    target ?? transitions[0] ?? ticket.status,
  );
  const [note, setNote] = useState("");
  const mutation = useStatusChange();
  const required =
    ["resolved", "cancelled"].includes(status) ||
    ["resolved", "cancelled"].includes(ticket.status);
  return (
    <Modal title={`Cambiar estado · ${ticket.code}`} onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!mutation.isPending)
            mutation.mutate(
              { ticket, status, note: note.trim() || undefined },
              { onSuccess: onClose },
            );
        }}
      >
        <label htmlFor="status">Nuevo estado</label>
        <select
          className="select"
          id="status"
          value={status}
          onChange={(e) => {
            const match = statuses.find((s) => s.code === e.target.value);
            if (match) setStatus(match.code);
          }}
        >
          {statuses
            .filter((s) => transitions.includes(s.code))
            .map((s) => (
              <option key={s.code} value={s.code}>
                {s.label}
              </option>
            ))}
        </select>
        <label htmlFor="note">
          {status === "resolved"
            ? "Nota de solución"
            : required
              ? "Motivo del cambio"
              : "Nota (opcional)"}
        </label>
        <textarea
          id="note"
          className="textarea"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          minLength={3}
          maxLength={1000}
          required={required}
        />
        <button
          className="btn btn-primary"
          disabled={mutation.isPending || transitions.length === 0}
        >
          Confirmar cambio
        </button>
      </form>
    </Modal>
  );
}
