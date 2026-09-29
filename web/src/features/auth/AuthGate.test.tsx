import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { db } from "../../mocks/handlers";
import { axeViolations, renderWithProviders } from "../../test/render";
import { AuthGate } from "./AuthGate";

describe("AuthGate", () => {
  it("lets a signed-in owner straight through (dev auth)", async () => {
    renderWithProviders(<AuthGate>private stuff</AuthGate>);
    expect(await screen.findByText("private stuff")).toBeInTheDocument();
  });

  it("requires password and then the 6-digit code", async () => {
    db.auth.signedIn = false;
    const user = userEvent.setup();
    const { container } = renderWithProviders(<AuthGate>private stuff</AuthGate>);

    await user.type(await screen.findByLabelText("Username"), "owner");
    await user.type(screen.getByLabelText("Password"), "wrong");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Wrong username or password");

    await user.clear(screen.getByLabelText("Password"));
    await user.type(screen.getByLabelText("Password"), "correct horse");
    await user.click(screen.getByRole("button", { name: "Continue" }));

    const code = await screen.findByLabelText(/6-digit code/);
    expect(await axeViolations(container)).toEqual([]);
    await user.type(code, "000000");
    await user.click(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("didn't work");

    await user.clear(code);
    await user.type(code, "123 456");
    await user.click(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByText("private stuff")).toBeInTheDocument();
    expect(screen.queryByText("private stuff")).toBeInTheDocument();
  });
});
