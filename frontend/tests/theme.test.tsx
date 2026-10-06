import { afterEach, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeProvider, useTheme } from "../src/components/ThemeProvider";

function Switch() {
  const { theme, toggle } = useTheme();
  return <button onClick={toggle}>{theme}</button>;
}
afterEach(() => {
  localStorage.removeItem("idl-tickets-theme");
  document.documentElement.dataset.theme = "light";
});
it("aplica el tema también a diálogos y conserva la elección al volver a entrar", async () => {
  localStorage.setItem("idl-tickets-theme", "light");
  const first = render(
    <ThemeProvider>
      <Switch />
    </ThemeProvider>,
  );
  await userEvent.click(screen.getByRole("button", { name: "light" }));
  expect(document.documentElement).toHaveAttribute("data-theme", "dark");
  expect(localStorage.getItem("idl-tickets-theme")).toBe("dark");
  first.unmount();
  render(
    <ThemeProvider>
      <Switch />
    </ThemeProvider>,
  );
  expect(screen.getByRole("button", { name: "dark" })).toBeVisible();
});
