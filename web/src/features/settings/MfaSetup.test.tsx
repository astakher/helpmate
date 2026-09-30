import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { db } from "../../mocks/handlers";
import { axeViolations, renderWithProviders } from "../../test/render";
import { MfaSetup } from "./MfaSetup";
import { SettingsPage } from "./SettingsPage";

describe("Two-step verification", () => {
  it("with the dev login, explains it isn't available instead of showing a QR code", async () => {
    const { container } = renderWithProviders(<MfaSetup />);
    expect(await screen.findByText(/Not available yet/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Set up authenticator app/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /QR code/ })).not.toBeInTheDocument();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("with a real login, stays off after scanning and turns on only with a matching code", async () => {
    db.auth.real = true;
    const user = userEvent.setup();
    const { container } = renderWithProviders(<SettingsPage />);

    await user.click(await screen.findByRole("button", { name: "Set up authenticator app" }));
    expect(await screen.findByRole("img", { name: /QR code/ })).toBeInTheDocument();
    expect(screen.getByText("MOCK SECR ETKE Y234")).toBeInTheDocument();
    expect(db.auth.mfaEnabled).toBe(false); // scanning alone changes nothing
    expect(await axeViolations(container)).toEqual([]);

    const input = screen.getByLabelText(/Enter the 6-digit code/);
    await user.type(input, "111111");
    await user.click(screen.getByRole("button", { name: "Turn on" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("doesn't match");
    expect(db.auth.mfaEnabled).toBe(false);

    await user.clear(input);
    await user.type(input, "24 68-10"); // only digits are kept
    expect(input).toHaveValue("246810");
    await user.click(screen.getByRole("button", { name: "Turn on" }));
    await waitFor(() => expect(db.auth.mfaEnabled).toBe(true));
    expect(await screen.findByText(/On\. You'll be asked for a code/)).toBeInTheDocument();
  });
});
