function interval(
  value: string | undefined,
  fallback: number,
  min: number,
  key: string,
) {
  const n = value === undefined ? fallback : Number(value);
  if (!Number.isFinite(n) || n < min || n > 60000)
    throw new Error(`${key} fuera de rango`);
  return n;
}
const raw = import.meta.env.VITE_API_BASE_URL;
if (!raw && !import.meta.env.VITEST) throw new Error("Falta VITE_API_BASE_URL");
const apiUrl = (raw ?? "http://localhost:5000/api/v1").replace(/\/+$/, "");
const parsed = new URL(apiUrl);
if (
  !["http:", "https:"].includes(parsed.protocol) ||
  parsed.pathname !== "/api/v1" ||
  parsed.search ||
  parsed.hash
)
  throw new Error(
    "VITE_API_BASE_URL debe ser URL completa terminada en /api/v1",
  );
if (location.protocol === "https:" && parsed.protocol !== "https:")
  throw new Error(
    "VITE_API_BASE_URL requiere HTTPS para evitar contenido mixto",
  );
const timezone = import.meta.env.VITE_TIMEZONE ?? "America/Montevideo";
if (timezone !== "America/Montevideo")
  throw new Error("VITE_TIMEZONE debe ser America/Montevideo");
export const env = {
  apiUrl,
  appName: import.meta.env.VITE_APP_NAME ?? "Tickets activos · IDL",
  timezone,
  namespace: "idl-visualizer-session",
  display: true,
  refreshMs: interval(
    import.meta.env.VITE_REFRESH_INTERVAL_MS,
    5000,
    1000,
    "VITE_REFRESH_INTERVAL_MS",
  ),
  pageMs: interval(
    import.meta.env.VITE_PAGE_INTERVAL_MS,
    15000,
    5000,
    "VITE_PAGE_INTERVAL_MS",
  ),
};
