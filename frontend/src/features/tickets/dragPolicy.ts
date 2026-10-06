import type { Status, StatusDefinition } from "../../types";

export function statusDropAction(
  from: Status,
  to: Status,
  statuses: StatusDefinition[],
) {
  if (from === to) return "none";
  if (
    !statuses.find((status) => status.code === from)?.transitions.includes(to)
  )
    return "reject";
  if (
    ["resolved", "cancelled"].includes(from) ||
    ["resolved", "cancelled"].includes(to)
  )
    return "note";
  return "move";
}
