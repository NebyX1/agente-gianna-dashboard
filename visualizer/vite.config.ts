import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react-swc";
import tailwind from "@tailwindcss/vite";
export default defineConfig(({ mode }) => {
  const env = { ...loadEnv(mode, process.cwd(), ""), ...process.env };
  const raw = env.VITE_API_BASE_URL;
  if (mode !== "test") {
    if (!raw) throw new Error("Falta VITE_API_BASE_URL");
    const url = new URL(raw);
    if (
      !["http:", "https:"].includes(url.protocol) ||
      url.pathname.replace(/\/$/, "") !== "/api/v1" ||
      url.search ||
      url.hash
    )
      throw new Error("VITE_API_BASE_URL debe terminar en /api/v1");
  }
  return {
    plugins: [react(), tailwind()],
    server: { port: 5174, strictPort: true, host: "0.0.0.0" },
    preview: { port: 5174, strictPort: true },
    test: {
      environment: "jsdom",
      setupFiles: ["./tests/setup.ts"],
      restoreMocks: true,
    },
  };
});
