import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// GitHub Pages serves the app from /olr-scout/; locally it is served from /.
export default defineConfig({
  base: process.env.VITE_BASE || "/",
  plugins: [react()],
  // No PostCSS plugins; keeps any parent-folder PostCSS config from applying.
  css: { postcss: { plugins: [] } },
  server: {
    port: 5173,
    proxy: { "/api": "http://localhost:8000", "/healthz": "http://localhost:8000" },
  },
});
