import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { db } from "../../mocks/handlers";
import { axeViolations, renderWithProviders } from "../../test/render";
import { NotificationSettingsForm } from "./SettingsPage";

describe("Notification settings", () => {
  it("turns the evening check-in on at a chosen time and keeps the other settings", async () => {
    db.settings = { ...db.settings, max_per_hour: 4, private_previews: true };
    const user = userEvent.setup();
    const { container } = renderWithProviders(<NotificationSettingsForm />);
    const checkin = await screen.findByRole("checkbox", { name: /summary each evening/ });
    expect(checkin).not.toBeChecked();
    expect(await axeViolations(container)).toEqual([]);

    await user.click(checkin);
    const time = screen.getByLabelText("At");
    await user.clear(time);
    await user.type(time, "21:30");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Saved");
    expect(db.settings).toMatchObject({ checkin_at: "21:30:00", max_per_hour: 4, private_previews: true });
  });

  it("turning it off sends no check-in time", async () => {
    db.settings = { ...db.settings, checkin_at: "20:00:00" };
    const user = userEvent.setup();
    renderWithProviders(<NotificationSettingsForm />);
    await user.click(await screen.findByRole("checkbox", { name: /summary each evening/ }));
    await user.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByRole("status");
    expect(db.settings.checkin_at).toBeNull();
  });
});
