import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// В dev-режиме (npm run dev) /api и /healthz уходят на backend; в Docker это делает nginx.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://localhost:8000", "/healthz": "http://localhost:8000" } },
});
