import type { DisplayTicket } from "../types";

// The spotlight is informational: it never changes the queue or assigns priority.
export function latestTicket(items: DisplayTicket[]): DisplayTicket | null {
  return items.reduce<DisplayTicket | null>((latest, ticket) => {
    if (!latest) return ticket;
    const difference =
      Date.parse(ticket.updated_at) - Date.parse(latest.updated_at);
    return difference > 0 || (difference === 0 && ticket.id > latest.id)
      ? ticket
      : latest;
  }, null);
}
