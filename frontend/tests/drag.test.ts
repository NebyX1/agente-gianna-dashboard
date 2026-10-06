import { describe, expect, it } from "vitest";
import { statusDropAction } from "../src/features/tickets/dragPolicy";
import type { StatusDefinition } from "../src/types";

const statuses: StatusDefinition[] = [
  { code: "new", label: "Nuevo", transitions: ["in_progress", "cancelled"] },
  {
    code: "in_progress",
    label: "En curso",
    transitions: ["waiting", "resolved", "cancelled"],
  },
  {
    code: "waiting",
    label: "En espera",
    transitions: ["in_progress", "resolved", "cancelled"],
  },
  { code: "resolved", label: "Resuelto", transitions: ["in_progress"] },
  { code: "cancelled", label: "Cancelado", transitions: ["new"] },
];
describe("movimientos entre columnas", () => {
  it("persiste estados activos permitidos y rechaza saltos inválidos", () => {
    expect(statusDropAction("new", "in_progress", statuses)).toBe("move");
    expect(statusDropAction("in_progress", "waiting", statuses)).toBe("move");
    expect(statusDropAction("new", "waiting", statuses)).toBe("reject");
    expect(statusDropAction("waiting", "waiting", statuses)).toBe("none");
  });
  it("mantiene las notas obligatorias al cerrar o reabrir", () => {
    expect(statusDropAction("in_progress", "resolved", statuses)).toBe("note");
    expect(statusDropAction("new", "cancelled", statuses)).toBe("note");
    expect(statusDropAction("resolved", "in_progress", statuses)).toBe("note");
    expect(statusDropAction("cancelled", "new", statuses)).toBe("note");
  });
});
