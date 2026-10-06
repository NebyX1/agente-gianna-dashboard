import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TicketForm } from "../src/components/TicketForm";
import { post } from "../src/api/axios";
import { refreshTickets } from "../src/api/hooks/useTickets";
import type { Catalogs, Ticket } from "../src/types";
vi.mock("../src/api/axios", () => ({
  post: vi.fn(),
  patch: vi.fn(),
  errorMessage: () => "Sin conexión",
  fieldErrors: () => ({}),
}));
vi.mock("../src/api/hooks/useTickets", () => ({ refreshTickets: vi.fn() }));
const unit = (id: number, code: string, name: string, receives: boolean) => ({
  id,
  code,
  name,
  kind: "area" as const,
  is_active: true,
  can_receive_tickets: receives,
  parent_id: null,
});
const catalogs: Catalogs = {
  org_units: [
    unit(1, "TI", "Informática", true),
    unit(2, "TR", "Tránsito", false),
  ],
  problem_types: [
    {
      id: 1,
      code: "IMP",
      name: "Impresora",
      description: null,
      is_active: true,
    },
  ],
  statuses: [],
  default_destination_unit_id: 1,
  warnings: [],
};
const result: Ticket = {
  id: 1,
  code: "IDL-TI-000001",
  origin_unit_id: 2,
  destination_unit_id: 1,
  problem_type_id: 1,
  description: "La impresora no imprime",
  status: "new",
  version: 1,
  created_by_user_id: 1,
  created_at: "2026-10-04T12:00:00Z",
  updated_at: "2026-10-04T12:00:00Z",
  occurred_at: null,
  resolved_at: null,
  cancelled_at: null,
  first_response_at: null,
  archived_at: null,
  archived_by_user_id: null,
  archive_reason: null,
  origin: catalogs.org_units[1],
  destination: catalogs.org_units[0],
  problem_type: catalogs.problem_types[0],
};
beforeEach(() => {
  vi.resetAllMocks();
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
});
describe("Formulario real", () => {
  it("bloquea controles, submit programático y Enter en la vista previa de Gianna", async () => {
    render(<TicketForm catalogs={catalogs} defaults={{origin_unit_id:2,problem_type_id:1,description:"La impresora no imprime"}} preview onClose={vi.fn()}/>);
    expect(screen.getByLabelText("Origen del pedido")).toBeDisabled();
    expect(screen.getByLabelText("Descripción del problema")).toBeDisabled();
    expect(screen.getByRole("button", {name:"Crear ticket"})).toBeDisabled();
    fireEvent.submit(screen.getByTestId("ticket-form"));
    fireEvent.keyDown(screen.getByTestId("ticket-form"), {key:"Enter",code:"Enter"});
    await new Promise(resolve=>setTimeout(resolve,30));
    expect(post).not.toHaveBeenCalled();
    expect(refreshTickets).not.toHaveBeenCalled();
  });
  it("precompleta origen/tipo sin crear y enfoca descripción inválida", async () => {
    render(
      <TicketForm
        catalogs={catalogs}
        defaults={{ origin_unit_id: 2, problem_type_id: 1 }}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByLabelText("Origen del pedido")).toHaveValue("2");
    expect(screen.getByLabelText("Destino responsable")).toHaveValue("1");
    expect(post).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Crear ticket" }));
    expect(
      await screen.findByText("Ingresá al menos 10 caracteres"),
    ).toBeVisible();
    await waitFor(() =>
      expect(screen.getByLabelText("Descripción del problema")).toHaveFocus(),
    );
  });
  it("conserva texto y clave frente a respuesta perdida y confirma una sola creación lógica", async () => {
    vi.mocked(post)
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(result);
    render(
      <TicketForm
        catalogs={catalogs}
        defaults={{ origin_unit_id: 2, problem_type_id: 1 }}
        onClose={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Descripción del problema"), {
      target: { value: result.description },
    });
    await userEvent.click(screen.getByRole("button", { name: "Crear ticket" }));
    const retry = await screen.findByRole("button", {
      name: "Reintentar el mismo intento",
    });
    expect(screen.getByLabelText("Descripción del problema")).toHaveValue(
      result.description,
    );
    await userEvent.click(retry);
    await waitFor(() => expect(refreshTickets).toHaveBeenCalled());
    expect(vi.mocked(post).mock.calls[0][2]).toBe(
      vi.mocked(post).mock.calls[1][2],
    );
    expect(vi.mocked(post).mock.calls[0][1]).toEqual(
      vi.mocked(post).mock.calls[1][1],
    );
  });
});
