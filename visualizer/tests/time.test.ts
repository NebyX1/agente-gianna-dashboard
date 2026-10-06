import { describe, expect, it } from "vitest";
import { age, formatDate } from "../src/utils/time";
describe("Montevideo explícito", () => {
  it("convierte Z y offset al mismo instante local", () => {
    expect(formatDate("2026-10-04T02:30:00Z")).toMatch(/3[/.]10[/.]26.*23:30/);
    expect(formatDate("2026-10-03T23:30:00-03:00")).toBe(
      formatDate("2026-10-04T02:30:00Z"),
    );
  });
  it("rechaza fechas ambiguas y conserva días anteriores", () => {
    expect(() => formatDate("2026-10-04T02:30:00")).toThrow();
    expect(
      age("2026-10-02T12:00:00Z", Date.parse("2026-10-04T12:00:00Z")),
    ).toBe("2 días");
  });
});
