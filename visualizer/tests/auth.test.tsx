import { beforeEach, expect, it, vi } from "vitest";
import { QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { act, render, screen } from "@testing-library/react";
import { SessionGate } from "../src/components/Auth";
import { useAuth } from "../src/store/auth";
import { queryClient } from "../src/api/queryClient";
import { clearSession, get } from "../src/api/axios";
vi.mock("../src/api/axios", async (importOriginal) => {
  const original = await importOriginal<typeof import("../src/api/axios")>();
  return { ...original, get: vi.fn() };
});
beforeEach(() => {
  queryClient.clear();
  useAuth.getState().clear();
});
it("valida la sesión persistida; un error de red no borra credenciales", async () => {
  useAuth.getState().login(
    "unit-token",
    {
      id: 1,
      name: "Viewer",
      email: "viewer@example.test",
      role: "viewer",
      is_active: true,
    },
    new Date(Date.now() + 14 * 3600000).toISOString(),
  );
  vi.mocked(get).mockRejectedValue(new Error("red caída"));
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <SessionGate>
          <p>Datos privados</p>
        </SessionGate>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(await screen.findByText("No se pudo validar la sesión")).toBeVisible();
  expect(useAuth.getState().token).toBe("unit-token");
  expect(screen.queryByText("Datos privados")).not.toBeInTheDocument();
});
it("limpia token, pending y Query cache al expirar o salir", () => {
  useAuth.getState().login(
    "unit-token",
    {
      id: 1,
      name: "Viewer",
      email: "viewer@example.test",
      role: "viewer",
      is_active: true,
    },
    new Date(Date.now() + 14 * 3600000).toISOString(),
  );
  useAuth.getState().setPending("pending-only-memory");
  queryClient.setQueryData(["tickets"], ["private"]);
  expect(localStorage.getItem("idl-visualizer-session")).not.toContain(
    "pending-only-memory",
  );
  clearSession("Sesión vencida");
  expect(useAuth.getState().token).toBeNull();
  expect(useAuth.getState().pending).toBeNull();
  expect(queryClient.getQueryData(["tickets"])).toBeUndefined();
});
it("vence automáticamente una sesión sin esperar un request al servidor", async () => {
  vi.useFakeTimers();
  try {
    const user = {
      id: 1,
      name: "Viewer",
      email: "viewer@example.test",
      role: "viewer" as const,
      is_active: true,
    };
    useAuth
      .getState()
      .login("unit-token", user, new Date(Date.now() + 1000).toISOString());
    vi.mocked(get).mockResolvedValue(user);
    queryClient.setQueryData(["tickets"], ["private"]);
    render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <SessionGate>
            <p>Datos privados</p>
          </SessionGate>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1100);
    });
    expect(useAuth.getState().token).toBeNull();
    expect(queryClient.getQueryData(["tickets"])).toBeUndefined();
    expect(screen.queryByText("Datos privados")).not.toBeInTheDocument();
  } finally {
    vi.useRealTimers();
  }
});
