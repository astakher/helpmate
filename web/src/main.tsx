import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";
import { App } from "./App";
import "./styles.css";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: true } },
});

async function start() {
  if (import.meta.env.VITE_API_MOCK === "1") {
    // `npm run dev:mock`: every /api call is answered in the browser by MSW (src/mocks)
    const { worker } = await import("./mocks/browser");
    await worker.start({ onUnhandledRequest: "bypass" });
  } else if (import.meta.env.PROD) {
    // Production build: register the PWA service worker (offline shell + push notifications)
    const { registerSW } = await import("virtual:pwa-register");
    registerSW({ immediate: true });
  }

  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </StrictMode>,
  );
}

void start();
