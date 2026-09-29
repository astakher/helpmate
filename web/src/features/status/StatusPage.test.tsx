import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "../../mocks/node";
import { renderWithProviders } from "../../test/render";
import { StatusPage } from "./StatusPage";

describe("StatusPage", () => {
  it("shows which seams are real and which are fake", async () => {
    server.use(
      http.get("*/api/health", () =>
        HttpResponse.json({
          status: "ok",
          version: "0.1.0",
          adapters: { llm: { name: "ollama:llama3.2:3b", fake: false }, repo: { name: "memory", fake: true } },
        }),
      ),
    );
    renderWithProviders(<StatusPage />);
    expect(await screen.findByText("ollama:llama3.2:3b")).toBeInTheDocument();
    expect(screen.getByText("REAL")).toBeInTheDocument();
    expect(screen.getByText("FAKE")).toBeInTheDocument();
  });

  it("explains when the API is down", async () => {
    server.use(http.get("*/api/health", () => HttpResponse.error()));
    renderWithProviders(<StatusPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("not reachable");
  });
});
