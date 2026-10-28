import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // No PostCSS plugins; keeps any parent-folder PostCSS config from applying.
  css: { postcss: { plugins: [] } },
  server: {
    port: 5173,
    proxy: { "/api": "http://localhost:8000", "/healthz": "http://localhost:8000" },
  },
});
