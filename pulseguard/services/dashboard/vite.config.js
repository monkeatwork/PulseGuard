import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the API calls go to a running stack's nginx (./run.sh),
// exactly the same /api/* paths the production build uses.
export default defineConfig({
  plugins: [react()],
  build: { chunkSizeWarningLimit: 900 },
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:3000" } },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.js",
  },
});
