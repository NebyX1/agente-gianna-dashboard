import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import tailwind from "@tailwindcss/vite";
export default defineConfig({ plugins: [react(), tailwind()], server: {port: 7861, strictPort: true},build:{rollupOptions:{output:{manualChunks:{audio:["@pipecat-ai/client-js","@pipecat-ai/small-webrtc-transport"]}}}} });
