import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect, useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { axeViolations } from "./test/render";
import { ErrorBoundary } from "./ErrorBoundary";

let broken = true;

function Flaky() {
  if (broken) throw new Error("render failed");
  return <p>All good</p>;
}

describe("ErrorBoundary", () => {
  beforeEach(() => {
    broken = true;
    vi.spyOn(console, "error").mockImplementation(() => {}); // React logs caught errors
  });
  afterEach(() => vi.restoreAllMocks());

  it("shows a message instead of a blank page, and Try again recovers", async () => {
    const user = userEvent.setup();
    const { container } = render(
      <ErrorBoundary>
        <Flaky />
      </ErrorBoundary>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Something went wrong");
    expect(screen.getByText("render failed")).toBeInTheDocument();
    expect(await axeViolations(container)).toEqual([]);

    broken = false;
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(screen.getByText("All good")).toBeInTheDocument();
  });

  it("clears the error when the reset key (the route) changes", () => {
    const { rerender } = render(
      <ErrorBoundary resetKey="/memory">
        <Flaky />
      </ErrorBoundary>,
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
    broken = false;
    rerender(
      <ErrorBoundary resetKey="/tasks">
        <Flaky />
      </ErrorBoundary>,
    );
    expect(screen.getByText("All good")).toBeInTheDocument();
  });

  it("also catches errors thrown in effects (the Sep 29 blank-page bug)", async () => {
    const user = userEvent.setup();
    function BadEffect() {
      const [n, setN] = useState(0);
      // the original bug: an expression-bodied effect returning a Promise, called as cleanup
      useEffect((() => Promise.resolve()) as unknown as () => void, [n]);
      return (
        <button type="button" onClick={() => setN(n + 1)}>
          again
        </button>
      );
    }
    render(
      <ErrorBoundary>
        <BadEffect />
      </ErrorBoundary>,
    );
    await user.click(screen.getByRole("button", { name: "again" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Something went wrong");
  });
});
