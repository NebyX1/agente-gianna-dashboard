import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { connectionState } from "../src/hooks/useConnectionState";
import { capacity, pageItems } from "../src/utils/rotation";
import { DisplayPage } from "../src/features/display/DisplayPage";
import { latestTicket } from "../src/utils/featured";
import type { DisplayTicket } from "../src/types";
function ticket(id: number, updated_at: string): DisplayTicket {
  return {
    id,
    code: `TKT-${id}`,
    status: "new",
    origin: { id: 1, name: "Tránsito" },
    destination: { id: 2, name: "Informática" },
    problem_type: { id: 1, name: "Impresora" },
    description_preview: "Prueba de seguimiento",
    created_at: "2026-10-03T12:00:00Z",
    updated_at,
  };
}
const mocks = vi.hoisted(() => ({ tickets: vi.fn(), config: vi.fn() }));
vi.mock("../src/hooks/useTickets", () => ({
  useTickets: mocks.tickets,
  useDisplayConfig: mocks.config,
}));
describe("conexión y rotación", () => {
  it("un HTTP fallido con navegador online nunca equivale a cola vacía o conexión sana", () => {
    expect(connectionState(false, true, 0, 50000, true)).toBe("error");
    expect(connectionState(true, true, 45000, 50000, true)).toBe("stale");
    expect(connectionState(true, false, 10000, 50000, true)).toBe("stale");
    expect(connectionState(true, false, 45000, 50000, true)).toBe("current");
  });
  it("todos los elementos aparecen sin reiniciar página por polling", () => {
    const all = Array.from({ length: 37 }, (_, index) => index);
    const seen = new Set<number>();
    for (let page = 0; page < 7; page++)
      pageItems([...all], page, 6).items.forEach((id) => seen.add(id));
    expect([...seen]).toEqual(all);
    expect(pageItems([...all], 3, 6).page).toBe(3);
    expect(capacity(1920, 945).size).toBe(6);
    expect(capacity(1920, 1080).size).toBe(9);
    expect(capacity(1366, 768).size).toBe(3);
    expect(capacity(3840, 2160).size).toBeGreaterThan(9);
  });
  it("destaca la última actualización sin reordenar ni quitar pendientes", () => {
    const items = [
      ticket(1, "2026-10-04T12:00:00Z"),
      ticket(2, "2026-10-04T10:00:00-03:00"),
      ticket(3, "2026-10-04T12:30:00Z"),
    ];
    expect(latestTicket(items)?.id).toBe(2);
    expect(items.map((item) => item.id)).toEqual([1, 2, 3]);
    expect(latestTicket([])).toBeNull();
    expect(latestTicket([items[0], ticket(4, items[0].updated_at)])?.id).toBe(
      4,
    );
  });
  it("mantiene destacado y grilla en una desconexión, sin simular datos actuales", () => {
    const items = [
      ticket(1, "2026-10-04T12:00:00Z"),
      ticket(2, "2026-10-04T13:00:00Z"),
    ];
    mocks.tickets.mockReturnValue({
      data: { items, total: 2 },
      error: new Error("HTTP 500"),
      isError: true,
      dataUpdatedAt: Date.now(),
      refetch: vi.fn(),
    });
    mocks.config.mockReturnValue({
      data: { statuses: [], destinations: [] },
      isError: false,
    });
    render(
      <MemoryRouter>
        <DisplayPage />
      </MemoryRouter>,
    );
    const featured = screen.getByRole("region", {
      name: "Ticket con la actualización más reciente",
    });
    expect(within(featured).getByText("TKT-2")).toBeVisible();
    const grid = screen.getByRole("region", { name: "Tickets de la página" });
    expect(within(grid).getByText("TKT-1")).toBeVisible();
    expect(within(grid).getByText("TKT-2")).toBeVisible();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Datos desactualizados",
    );
  });
  it("muestra error de primera carga en lugar de no hay tickets", () => {
    mocks.tickets.mockReturnValue({
      data: undefined,
      error: new Error("HTTP 500"),
      isError: true,
      dataUpdatedAt: 0,
      refetch: vi.fn(),
    });
    mocks.config.mockReturnValue({
      data: { statuses: [], destinations: [] },
      isError: false,
    });
    render(
      <MemoryRouter>
        <DisplayPage />
      </MemoryRouter>,
    );
    expect(screen.getByText("Información no disponible")).toBeVisible();
    expect(
      screen.queryByText(/No hay tickets activos/),
    ).not.toBeInTheDocument();
  });
});
