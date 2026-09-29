import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import axe from "axe-core";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router";

export function renderWithProviders(ui: ReactElement, { route = "/" } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

/** axe accessibility violations (contrast is skipped: jsdom has no layout engine). */
export async function axeViolations(container: Element) {
  const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
  return results.violations.map((v) => `${v.id}: ${v.help}`);
}
