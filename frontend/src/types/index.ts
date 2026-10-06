import type { components } from "./contract";
export type Ticket = components["schemas"]["TicketRead"];
export type DisplayTicket = components["schemas"]["DisplayTicket"];
export type OrgUnit = components["schemas"]["OrgUnit"];
export type ProblemType = components["schemas"]["ProblemType"];
export type User = components["schemas"]["User"];
export type TicketInput = components["schemas"]["TicketCreate"];
export type TicketEvent = components["schemas"]["TicketEvent"];
export type Status = Ticket["status"];
export type StatusDefinition = {
  code: Status;
  label: string;
  transitions: Status[];
};
export type Catalogs = {
  org_units: OrgUnit[];
  problem_types: ProblemType[];
  statuses: StatusDefinition[];
  default_destination_unit_id: number | null;
  warnings: string[];
};
export type Page<T> = {
  items: T[];
  page: number;
  per_page: number;
  total: number;
  pages: number;
};
export type Envelope<T> = { ok: true; data: T; meta: { request_id: string } };
export type Group = { id: number; name: string; count: number };
export type Summary = {
  created: number;
  resolved: number;
  cancelled: number;
  archived: number;
  average_resolution_seconds: number | null;
  active_by_status: Record<string, number>;
  daily: { date: string; count: number }[];
  origins: Group[];
  destinations: Group[];
  definition: string;
};
