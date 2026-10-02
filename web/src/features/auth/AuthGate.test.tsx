import { focusManager } from "@tanstack/react-query";
import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { db } from "../../mocks/handlers";
import { server } from "../../mocks/node";
import { axeViolations, renderWithProviders } from "../../test/render";
import { AuthGate } from "./AuthGate";

async function passwordStep(user: ReturnType<typeof userEvent.setup>) {
  await user.type(await screen.findByLabelText("Username"), "owner");
  await user.type(screen.getByLabelText("Password"), "correct horse");
  await user.click(screen.getByRole("button", { name: "Continue" }));
  return screen.findByLabelText(/6-digit code/);
}

describe("AuthGate", () => {
  it("keeps the code step while the owner is in the authenticator app", async () => {
    db.auth.signedIn = false;
    const user = userEvent.setup();
    renderWithProviders(<AuthGate>private stuff</AuthGate>);
    await passwordStep(user);

    // leaving for the authenticator app and coming back: the app regains focus and re-checks
    // /api/me, which takes a moment on a phone (the old screen showed "Loading" meanwhile)
    let meChecks = 0;
    server.use(
      http.get("*/api/me", async () => {
        meChecks += 1;
        await delay(50);
        return db.auth.signedIn
          ? HttpResponse.json({ id: "owner", display_name: "Owner (mock)", mfa_enabled: true })
          : HttpResponse.json({ detail: "login required" }, { status: 401 });
      }),
    );
    act(() => {
      focusManager.setFocused(false);
      focusManager.setFocused(true);
    });
    await waitFor(() => expect(meChecks).toBe(1));
    expect(screen.queryByText("Loading HelpMate…")).not.toBeInTheDocument();
    await act(() => delay(80));
    focusManager.setFocused(undefined);

    expect(screen.getByLabelText(/6-digit code/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
    await user.type(screen.getByLabelText(/6-digit code/), "123456");
    await user.click(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByText("private stuff")).toBeInTheDocument();
  });

  it("brings the code step back after the app reloads, until the challenge expires", async () => {
    db.auth.signedIn = false;
    const user = userEvent.setup();
    const first = renderWithProviders(<AuthGate>private stuff</AuthGate>);
    await passwordStep(user);
    first.unmount(); // iOS reloaded the home-screen app while the owner was away

    const second = renderWithProviders(<AuthGate>private stuff</AuthGate>);
    await user.type(await screen.findByLabelText(/6-digit code/), "123456");
    await user.click(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByText("private stuff")).toBeInTheDocument();
    expect(localStorage.getItem("helpmate.login.challenge")).toBeNull(); // used up
    second.unmount();

    db.auth.signedIn = false;
    localStorage.setItem("helpmate.login.challenge", JSON.stringify({ id: "challenge-1", expires: Date.now() - 1 }));
    renderWithProviders(<AuthGate>private stuff</AuthGate>);
    expect(await screen.findByLabelText("Username")).toBeInTheDocument(); // expired: password again
  });

  it("can start the sign-in over from the code step", async () => {
    db.auth.signedIn = false;
    const user = userEvent.setup();
    renderWithProviders(<AuthGate>private stuff</AuthGate>);
    await passwordStep(user);
    await user.click(screen.getByRole("button", { name: "Start over" }));
    expect(await screen.findByLabelText("Username")).toBeInTheDocument();
    expect(localStorage.getItem("helpmate.login.challenge")).toBeNull();
  });

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

  it("can show the password while typing it, and hide it again", async () => {
    db.auth.signedIn = false;
    const user = userEvent.setup();
    const { container } = renderWithProviders(<AuthGate>private stuff</AuthGate>);
    const password = await screen.findByLabelText("Password");
    await user.type(password, "correct horse");
    expect(password).toHaveAttribute("type", "password");

    await user.click(screen.getByRole("button", { name: "Show password" }));
    expect(password).toHaveAttribute("type", "text");
    expect(password).toHaveValue("correct horse");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument(); // the toggle doesn't submit
    expect(await axeViolations(container)).toEqual([]);

    await user.click(screen.getByRole("button", { name: "Hide password" }));
    expect(password).toHaveAttribute("type", "password");
  });
});
