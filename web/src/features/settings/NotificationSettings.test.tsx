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
    const time = screen.getByLabelText("At (evening check-in)");
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

describe("Morning brief and weekly review", () => {
  it("are off by default and each turns on with its own time (and day)", async () => {
    const user = userEvent.setup();
    const { container } = renderWithProviders(<NotificationSettingsForm />);
    const brief = await screen.findByRole("checkbox", { name: /summary each morning/ });
    const review = screen.getByRole("checkbox", { name: /look back once a week/ });
    expect(brief).not.toBeChecked();
    expect(review).not.toBeChecked();
    expect(await axeViolations(container)).toEqual([]);

    await user.click(brief);
    await user.clear(screen.getByLabelText("At (morning brief)"));
    await user.type(screen.getByLabelText("At (morning brief)"), "07:15");
    await user.click(review);
    await user.selectOptions(screen.getByLabelText("On (weekly review day)"), "Friday");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Saved");
    expect(db.settings).toMatchObject({
      morning_brief_at: "07:15:00",
      weekly_review_at: "18:00:00", // the suggested time
      weekly_review_day: 4, // Monday = 0
      checkin_at: null, // untouched
    });
  });

  it("turning them off again sends no time", async () => {
    db.settings = { ...db.settings, morning_brief_at: "07:30:00", weekly_review_at: "18:00:00" };
    const user = userEvent.setup();
    renderWithProviders(<NotificationSettingsForm />);
    await user.click(await screen.findByRole("checkbox", { name: /summary each morning/ }));
    await user.click(screen.getByRole("checkbox", { name: /look back once a week/ }));
    await user.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByRole("status");
    expect(db.settings).toMatchObject({ morning_brief_at: null, weekly_review_at: null });
  });
});
