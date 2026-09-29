/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

// Modes:
//   npm run dev       -> real backend on 127.0.0.1:8000 (running its fakes or real adapters)
//   npm run dev:mock  -> MSW mocks in the browser, no backend needed
// The PWA service worker is only built for production. In dev it is disabled so it never
// fights MSW's worker for the "/" scope.
export default defineConfig(({ mode }) => ({
  define: {
    "import.meta.env.VITE_API_MOCK": JSON.stringify(mode === "mock" ? "1" : "0"),
  },
  plugins: [
    react(),
    VitePWA({
      strategies: "injectManifest",
      srcDir: "src",
      filename: "sw.ts",
      registerType: "autoUpdate",
      injectRegister: false,
      devOptions: { enabled: false },
      injectManifest: { globIgnores: ["**/mockServiceWorker.js"] },
      manifest: {
        name: "HelpMate",
        short_name: "HelpMate",
        description: "Your local-first personal assistant",
        start_url: "/",
        scope: "/",
        display: "standalone",
        background_color: "#f6f7f5",
        theme_color: "#1f5f5b",
        icons: [
          { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
          { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
        ],
      },
    }),
  ],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: false } },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
}));
