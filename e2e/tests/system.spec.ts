import { test, expect, type Page, type Browser } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { readFileSync } from "node:fs";
import { randomUUID } from "node:crypto";
const credentials = JSON.parse(
  readFileSync(
    process.env.E2E_CREDENTIALS_FILE ??
      new URL("../.test-users.json", import.meta.url),
    "utf8",
  ),
) as Record<
  "admin" | "operator" | "viewer",
  { email: string; password: string }
>;
const base = process.env.E2E_API_URL ?? "http://localhost:5300/api/v1";
const frontendUrl = process.env.E2E_FRONTEND_URL ?? "http://localhost:5373";
const displayUrl = process.env.E2E_DISPLAY_URL ?? "http://localhost:5374";
const mailUrl = process.env.E2E_MAIL_URL ?? "http://localhost:8026";
async function otp(email: string) {
  for (let i = 0; i < 30; i++) {
    const response = await fetch(`${mailUrl}/api/v1/messages`);
    const messages = (await response.json()) as {
      messages: { ID: string; To: { Address: string }[] }[];
    };
    const match = messages.messages.find((m) =>
      m.To.some((to) => to.Address === email),
    );
    if (match) {
      const mail = (await (
        await fetch(`${mailUrl}/api/v1/message/${match.ID}`)
      ).json()) as { Text: string };
      const code = mail.Text.match(/\b\d{6}\b/)?.[0];
      if (code) return code;
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error("No llegó OTP al transporte SMTP Mailpit");
}
async function login(
  page: Page,
  role: "admin" | "operator" | "viewer",
  display = false,
) {
  await page.goto(`${display ? displayUrl : frontendUrl}/login`);
  await page.getByLabel("Correo electrónico").fill(credentials[role].email);
  await page
    .getByLabel("Contraseña", { exact: true })
    .fill(credentials[role].password);
  await page.getByRole("button", { name: "Continuar →" }).click();
  await expect(page.getByLabel("Código de verificación")).toBeVisible();
  await page
    .getByLabel("Código de verificación")
    .fill(await otp(credentials[role].email));
  await page.getByRole("button", { name: "Verificar e ingresar" }).click();
  await expect(page).toHaveURL(new RegExp(display ? "/pantalla" : "/tickets"));
}
async function access(page: Page, display = false) {
  return page.evaluate(
    (key) =>
      JSON.parse(localStorage.getItem(key) ?? "{}").state.token as string,
    display ? "idl-visualizer-session" : "idl-frontend-session",
  );
}
async function request(
  page: Page,
  method: string,
  path: string,
  data?: unknown,
  display = false,
  key?: string,
) {
  const response = await fetch(base + path, {
    method,
    headers: {
      Authorization: `Bearer ${await access(page, display)}`,
      "Content-Type": "application/json",
      ...(key ? { "Idempotency-Key": key } : {}),
    },
    body: data === undefined ? undefined : JSON.stringify(data),
  });
  return { status: response.status, body: await response.json() };
}
type Ticket = {
  id: number;
  code: string;
  version: number;
  status: string;
  origin_unit_id: number;
  destination_unit_id: number;
  problem_type_id: number;
  description: string;
};
async function contexts(browser: Browser) {
  const operator = await browser.newContext({
    viewport: { width: 1600, height: 1000 },
  });
  const viewer = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
  });
  return {
    operator,
    viewer,
    op: await operator.newPage(),
    tv: await viewer.newPage(),
  };
}
test.describe.serial("producto real · MariaDB + Flask + Nginx + SMTP", () => {
  let sessions: Awaited<ReturnType<typeof contexts>>;
  let ticket: Ticket;
  let longOrigin: number;
  let longType: number;
  test.beforeAll(async ({ browser }) => {
    sessions = await contexts(browser);
    await login(sessions.op, "operator");
    await login(sessions.tv, "viewer", true);
  });
  test.afterAll(async () => {
    await sessions.operator.close();
    await sessions.viewer.close();
  });
  test("arrastre precompleta, confirma una sola alta y propaga a TV", async () => {
    const { op, tv } = sessions;
    const catalog = (await request(op, "GET", "/catalogs")).body.data;
    const kind = catalog.problem_types.find(
      (t: { code: string }) => t.code === "IMPRESORA",
    );
    const origin = catalog.org_units.find(
      (u: { code: string }) => u.code === "TRANSITO",
    );
    await op
      .getByRole("button", { name: "Creación rápida", exact: true })
      .click();
    await op.getByLabel("Origen solicitante", { exact: true }).fill("Tránsito");
    const handle = op.getByTestId(`problem-${kind.id}`);
    const target = op.getByTestId(`origin-${origin.id}`);
    const from = await handle.boundingBox();
    const to = await target.boundingBox();
    if (!from || !to) throw new Error("Tarjetas no visibles");
    await op.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
    await op.mouse.down();
    await op.mouse.move(to.x + to.width / 2, to.y + to.height / 2, {
      steps: 18,
    });
    await expect(
      op.getByRole("dialog").getByTestId("quick-drag-preview"),
    ).toBeVisible();
    await op.mouse.up();
    await expect(op.getByRole("dialog")).toBeVisible();
    await expect(op.getByLabel("Origen del pedido")).toHaveValue(
      String(origin.id),
    );
    await expect(
      op.getByRole("dialog").getByLabel("Tipo de problema"),
    ).toHaveValue(String(kind.id));
    const description =
      "Prueba E2E por arrastre: impresora de Tránsito no imprime " +
      randomUUID();
    await op.getByLabel("Descripción del problema").fill(description);
    await op.screenshot({
      path: "test-results/formulario.png",
      fullPage: false,
    });
    const response = op.waitForResponse(
      (r) => r.url() === base + "/tickets" && r.request().method() === "POST",
    );
    await op
      .getByRole("button", { name: "Crear ticket", exact: true })
      .dblclick();
    ticket = (await (await response).json()).data as Ticket;
    await expect(op.getByRole("dialog")).not.toBeVisible();
    const matching = await request(
      op,
      "GET",
      "/tickets?q=" + encodeURIComponent(description),
    );
    expect(matching.body.data.total).toBe(1);
    // Poll interval 1 s + explicit local tolerance 9 s.
    await expect(
      tv.locator(".display-grid").getByText(ticket.code, { exact: true }),
    ).toBeVisible({
      timeout: 10000,
    });
    const history = await request(op, "GET", `/tickets/${ticket.id}/history`);
    expect(history.body.data.items).toHaveLength(1);
  });
  test("edita, cambia estados, resuelve y reabre con propagación", async () => {
    const { op, tv } = sessions;
    await op.goto(`${frontendUrl}/tickets/${ticket.id}`);
    await op.getByRole("button", { name: "Editar ticket" }).click();
    await op
      .getByLabel("Descripción del problema")
      .fill("Descripción editada: se escucha un ruido raro al imprimir");
    await op.getByRole("button", { name: "Guardar cambios" }).click();
    await expect(op.getByRole("dialog")).not.toBeVisible();
    async function move(label: string, note?: string) {
      await op
        .getByRole("button", { name: "Cambiar estado", exact: true })
        .click();
      await op.getByLabel("Nuevo estado").selectOption({ label });
      if (note) await op.getByRole("textbox").fill(note);
      await op.getByRole("button", { name: "Confirmar cambio" }).click();
      await expect(op.getByRole("dialog")).not.toBeVisible();
    }
    await move("En curso");
    await expect(
      tv
        .locator("article")
        .filter({ hasText: ticket.code })
        .getByText("En curso"),
    ).toBeVisible();
    await move("En espera");
    await expect(
      tv
        .locator("article")
        .filter({ hasText: ticket.code })
        .getByText("En espera"),
    ).toBeVisible();
    await move("Resuelto", "Se retiró papel atascado y se probó la impresión");
    await expect(
      tv.locator(".display-grid").getByText(ticket.code, { exact: true }),
    ).not.toBeVisible();
    await move("En curso", "Se repitió la falla en una nueva impresión");
    await expect(
      tv.locator(".display-grid").getByText(ticket.code, { exact: true }),
    ).toBeVisible();
  });
  test("arrastra la tarjeta completa, guarda, mueve con teclado y exige nota al cerrar", async () => {
    const { op, tv } = sessions;
    await op.goto(`${frontendUrl}/tickets`);
    const card = op.getByTestId(`card-${ticket.code}`);
    async function dragTo(status: string) {
      await expect(card).toBeVisible();
      const from = await card.getByRole("heading").boundingBox();
      const to = await op.getByTestId(`column-${status}`).boundingBox();
      if (!from || !to) throw new Error("Tablero no visible");
      await op.mouse.move(from.x + from.width / 2, from.y + from.height / 2);
      await op.mouse.down();
      await op.mouse.move(to.x + to.width / 2, to.y + 100, { steps: 18 });
      await expect(op.getByTestId("drag-preview")).toBeVisible();
      await op.mouse.up();
    }
    await dragTo("waiting");
    await expect(
      op.getByTestId("column-waiting").getByTestId(`card-${ticket.code}`),
    ).toBeVisible();
    await expect(op.getByRole("dialog")).not.toBeVisible();
    await expect
      .poll(
        async () =>
          (await request(op, "GET", `/tickets/${ticket.id}`)).body.data.status,
      )
      .toBe("waiting");
    await expect(
      tv
        .locator("article")
        .filter({ hasText: ticket.code })
        .getByText("En espera"),
    ).toBeVisible();
    await op.reload();
    await expect(
      op.getByTestId("column-waiting").getByTestId(`card-${ticket.code}`),
    ).toBeVisible();
    const draggable = op.getByTestId(`draggable-ticket-${ticket.id}`);
    await draggable.focus();
    await op.keyboard.press("Space");
    await expect(op.getByTestId("drag-preview")).toBeVisible();
    await op.keyboard.press("ArrowLeft");
    await expect(op.getByTestId("column-in_progress")).toHaveClass(/drop-over/);
    await op.keyboard.press("Space");
    await expect
      .poll(
        async () =>
          (await request(op, "GET", `/tickets/${ticket.id}`)).body.data.status,
      )
      .toBe("in_progress");
    await expect(
      op.getByTestId("column-in_progress").getByTestId(`card-${ticket.code}`),
    ).toBeVisible();
    const before = (await request(op, "GET", `/tickets/${ticket.id}`)).body
      .data;
    await dragTo("new");
    await expect(op.getByRole("alert")).toContainText("no está permitido");
    expect(
      (await request(op, "GET", `/tickets/${ticket.id}`)).body.data.version,
    ).toBe(before.version);
    await op.getByLabel("Filtrar por estado").selectOption("");
    await dragTo("resolved");
    await expect(op.getByRole("dialog")).toBeVisible();
    await expect(op.getByLabel("Nuevo estado")).toHaveValue("resolved");
    await expect(op.getByRole("dialog").getByRole("textbox")).toBeVisible();
    expect(
      (await request(op, "GET", `/tickets/${ticket.id}`)).body.data.status,
    ).toBe("in_progress");
    await op.keyboard.press("Escape");
    await op.getByLabel("Filtrar por estado").selectOption("active");
    await op.getByRole("link", { name: ticket.code, exact: true }).click();
    await expect(op).toHaveURL(new RegExp(`/tickets/${ticket.id}$`));
  });
  test("tema nocturno persistente, filtros simples, lista y diseño móvil accesible", async () => {
    const { op } = sessions;
    await op.goto(`${frontendUrl}/tickets`);
    const theme = op.getByRole("button", { name: "Modo nocturno" });
    await expect(theme).toHaveAttribute("aria-pressed", "false");
    await expect(op.getByLabel("Filtrar por origen")).not.toBeVisible();
    await op.getByRole("button", { name: "Filtros", exact: true }).click();
    await expect(op.getByLabel("Filtrar por origen")).toBeVisible();
    await op
      .getByLabel("Filtrar por origen")
      .selectOption(String(ticket.origin_unit_id));
    await op.getByRole("button", { name: "Limpiar", exact: true }).click();
    await expect(op.getByLabel("Filtrar por origen")).toHaveValue("");
    await op.getByRole("button", { name: "Filtros", exact: true }).click();
    await op.getByRole("button", { name: "Vista de lista" }).click();
    await expect(
      op.getByRole("table", { name: "Lista de tickets" }),
    ).toBeVisible();
    await expect(op.getByTestId(`row-${ticket.code}`)).toBeVisible();
    await expect(
      op.getByRole("button", { name: "Vista de lista" }),
    ).toHaveAttribute("aria-pressed", "true");
    await op.getByRole("button", { name: "Vista de tablero" }).click();
    await op.screenshot({ path: "test-results/operacion-clara.png" });
    async function audit() {
      const result = await new AxeBuilder({ page: op })
        .withTags(["wcag2a", "wcag2aa"])
        .analyze();
      expect(
        result.violations
          .filter((v) => v.impact === "critical" || v.impact === "serious")
          .map((v) => ({
            id: v.id,
            nodes: v.nodes.map((n) => ({
              target: n.target,
              summary: n.failureSummary,
            })),
          })),
      ).toEqual([]);
    }
    await audit();
    await theme.click();
    await expect(op.locator("html")).toHaveAttribute("data-theme", "dark");
    await op.reload();
    await expect(theme).toHaveAttribute("aria-pressed", "true");
    await expect(op.locator("html")).toHaveAttribute("data-theme", "dark");
    await expect(op.getByTestId(`card-${ticket.code}`)).toBeVisible();
    await op.screenshot({ path: "test-results/operacion-neon.png" });
    await audit();
    await op.getByRole("button", { name: "Nuevo ticket", exact: true }).click();
    await expect(op.getByRole("dialog").locator(".modal-box")).toHaveCSS(
      "background-color",
      "rgb(16, 24, 39)",
    );
    await audit();
    await op.keyboard.press("Escape");
    await expect(op.getByRole("dialog")).not.toBeVisible();
    await op.setViewportSize({ width: 375, height: 812 });
    await expect
      .poll(
        async () =>
          await op.evaluate(() => document.documentElement.scrollWidth),
      )
      .toBeLessThanOrEqual(375);
    await expect(
      op.getByRole("button", { name: "Nuevo ticket", exact: true }),
    ).toBeVisible();
    await op.screenshot({
      path: "test-results/operacion-movil.png",
      fullPage: true,
    });
    await audit();
    await op.setViewportSize({ width: 1600, height: 1000 });
    await op.getByRole("link", { name: "Estadísticas", exact: true }).click();
    await expect(
      op.getByRole("heading", {
        name: "Problemas que se repiten",
        exact: true,
      }),
    ).toBeVisible();
    await audit();
    await op.getByRole("link", { name: "Solicitudes", exact: true }).click();
    await op.getByRole("link", { name: ticket.code, exact: true }).click();
  });
  test("oculta con comprobante, admin consulta historia y restaura", async ({
    browser,
  }) => {
    const { op, tv } = sessions;
    await op.getByRole("button", { name: "Ocultar ticket" }).click();
    await op
      .getByLabel("Motivo", { exact: true })
      .fill("Duplicado confirmado en prueba E2E");
    await op.getByRole("button", { name: "Confirmar ocultación" }).click();
    await expect(op).toHaveURL(/\/tickets$/);
    await expect(
      tv.locator(".display-grid").getByText(ticket.code, { exact: true }),
    ).not.toBeVisible();
    expect(
      (await request(op, "GET", `/tickets/${ticket.id}/history`)).status,
    ).toBe(404);
    const admin = await browser.newPage();
    await login(admin, "admin");
    await admin.goto(`${frontendUrl}/admin/archived`);
    await admin.getByRole("link", { name: ticket.code, exact: true }).click();
    await expect(
      admin.getByText("Ticket ocultado", { exact: true }),
    ).toBeVisible();
    await admin.getByRole("button", { name: "Restaurar ticket" }).click();
    await admin
      .getByLabel("Motivo", { exact: true })
      .fill("Restauración de prueba para continuar seguimiento");
    await admin.getByRole("button", { name: "Confirmar restauración" }).click();
    await expect(admin.getByRole("dialog")).not.toBeVisible();
    await expect(
      tv.locator(".display-grid").getByText(ticket.code, { exact: true }),
    ).toBeVisible();
    const unit = await request(admin, "POST", "/admin/org-units", {
      code: "E2E_LONG",
      name: "Oficina de coordinación territorial y seguimiento de servicios municipales de Lavalleja",
      kind: "office",
    });
    expect(unit.status).toBe(201);
    longOrigin = unit.body.data.id;
    const kind = await request(admin, "POST", "/admin/problem-types", {
      code: "E2E_LONG",
      name: "Acceso intermitente a sistemas de gestión y plataformas institucionales de atención al público",
    });
    expect(kind.status).toBe(201);
    longType = kind.body.data.id;
    await admin.close();
  });
  test("conflicto de operadores, permisos viewer, error HTTP, desconexión y recuperación", async () => {
    const { op, tv, viewer } = sessions;
    const current: Ticket = (await request(op, "GET", `/tickets/${ticket.id}`))
      .body.data;
    const body = {
      origin_unit_id: current.origin_unit_id,
      destination_unit_id: current.destination_unit_id,
      problem_type_id: current.problem_type_id,
      description: "Cambio concurrente desde segundo operador de prueba",
      version: current.version,
    };
    const responses = await Promise.all([
      request(op, "PATCH", `/tickets/${ticket.id}`, body),
      request(op, "PATCH", `/tickets/${ticket.id}`, {
        ...body,
        description: "Cambio concurrente de otra persona del equipo",
      }),
    ]);
    expect(responses.map((r) => r.status).sort()).toEqual([200, 409]);
    expect(
      (await request(tv, "POST", "/tickets", body, true, randomUUID())).status,
    ).toBe(403);
    expect((await request(tv, "GET", "/tickets", undefined, true)).status).toBe(
      403,
    );
    await tv.route("**/api/v1/display/tickets*", (route) =>
      route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({
          ok: false,
          error: {
            code: "test_failure",
            message: "Fallo HTTP inducido",
            errors: {},
          },
          meta: { request_id: randomUUID() },
        }),
      }),
    );
    await expect(tv.getByText(/Datos desactualizados/)).toBeVisible();
    await expect(
      tv.locator(".display-grid").getByText(ticket.code, { exact: true }),
    ).toBeVisible();
    await tv.unroute("**/api/v1/display/tickets*");
    await expect(tv.getByText("● Actualizado")).toBeVisible();
    await viewer.setOffline(true);
    await expect(tv.getByText(/Datos desactualizados/)).toBeVisible();
    await tv.screenshot({
      path: "test-results/pantalla-sin-conexion.png",
      fullPage: true,
    });
    await viewer.setOffline(false);
    await expect(tv.getByText("● Actualizado")).toBeVisible();
    await op.goto(`${frontendUrl}/tickets`);
    await expect(
      op.getByRole("button", { name: "Nuevo ticket", exact: true }),
    ).toBeEnabled();
    await op.getByRole("button", { name: "Nuevo ticket", exact: true }).focus();
    await op.keyboard.press("Enter");
    await expect(op.getByRole("dialog")).toBeVisible();
    await op.keyboard.press("Escape");
    await expect(
      op.getByRole("button", { name: "Nuevo ticket", exact: true }),
    ).toBeFocused();
  });
  test("cola grande rota completa, día anterior sigue activo, capturas y accesibilidad", async () => {
    const { op, tv } = sessions;
    const catalog = (await request(op, "GET", "/catalogs")).body.data;
    const created: string[] = [];
    for (let i = 0; i < 16; i++) {
      const result = await request(
        op,
        "POST",
        "/tickets",
        {
          origin_unit_id: longOrigin,
          destination_unit_id: catalog.default_destination_unit_id,
          problem_type_id: longType,
          description: `Prueba de cola ${i}: ${"Descripción larga de una falla repetida en equipos. ".repeat(12)}`,
        },
        false,
        randomUUID(),
      );
      expect(result.status).toBe(201);
      created.push(result.body.data.code);
    }
    const all = (await request(tv, "GET", "/display/tickets", undefined, true))
      .body.data.items as {
      code: string;
      created_at: string;
      description_preview: string;
    }[];
    expect(
      all.some((t) => t.description_preview.includes("día anterior")),
    ).toBe(true);
    const seen = new Set<string>();
    const deadline = Date.now() + 27000;
    while (Date.now() < deadline && !created.every((code) => seen.has(code))) {
      for (const code of await tv
        .locator(".display-ticket-top > strong")
        .allTextContents())
        seen.add(code);
      await tv.waitForTimeout(500);
    }
    expect(created.every((code) => seen.has(code))).toBe(true);
    for (const size of [
      { width: 1920, height: 1080 },
      { width: 1366, height: 768 },
      { width: 3840, height: 2160 },
    ]) {
      await tv.setViewportSize(size);
      expect(
        await tv.evaluate(
          () => getComputedStyle(document.documentElement).fontSize,
        ),
      ).toBe(size.width >= 3000 ? "27px" : "16px");
      await expect(
        tv.locator(".display-grid").getByText(all[0].code, { exact: true }),
      ).toBeVisible({ timeout: 12000 });
      await tv.screenshot({
        path: `test-results/pantalla-${size.width}.png`,
        fullPage: true,
      });
      expect(
        await tv.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      expect(
        await tv.evaluate(
          () => document.documentElement.scrollHeight <= innerHeight,
        ),
      ).toBe(true);
    }
    await op.screenshot({
      path: "test-results/operacion.png",
      fullPage: false,
    });
    for (const page of [op, tv]) {
      const audit = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa"])
        .analyze();
      expect(
        audit.violations
          .filter((v) => v.impact === "critical" || v.impact === "serious")
          .map((v) => ({
            id: v.id,
            nodes: v.nodes.map((n) => ({
              target: n.target,
              summary: n.failureSummary,
            })),
          })),
      ).toEqual([]);
    }
  });
  test("Nginx rutas directas, assets 404, build API y revocación de pantalla", async () => {
    const { op, tv } = sessions;
    await op.reload();
    await expect(
      op.getByRole("heading", { name: "Solicitudes del equipo" }),
    ).toBeVisible();
    await tv.reload();
    await expect(
      tv.getByRole("heading", { name: "Tickets activos · IDL" }),
    ).toBeVisible();
    for (const url of [frontendUrl, displayUrl]) {
      expect((await fetch(`${url}/assets/missing.js`)).status).toBe(404);
      expect((await fetch(`${url}/api/v1/tickets`)).status).toBe(404);
      expect((await fetch(`${url}/healthz`)).status).toBe(200);
    }
    expect((await request(tv, "POST", "/auth/logout", {}, true)).status).toBe(
      200,
    );
    await expect(tv).toHaveURL(/\/login$/, { timeout: 10000 });
    await expect(tv.getByText(/La sesión venció o fue revocada/)).toBeVisible();
    expect(await tv.locator(".display-ticket").count()).toBe(0);
  });
});
