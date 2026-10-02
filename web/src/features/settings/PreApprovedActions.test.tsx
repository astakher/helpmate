import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { db } from "../../mocks/handlers";
import { axeViolations, renderWithProviders } from "../../test/render";
import { PreApprovedActions } from "./SettingsPage";

describe("Pre-approved actions", () => {
  it("start empty, offer only actions on HelpMate's own data, and save the owner's choice", async () => {
    const user = userEvent.setup();
    const { container } = renderWithProviders(<PreApprovedActions />);
    const group = await screen.findByRole("group", { name: "Do these without asking" });
    const boxes = within(group).getAllByRole("checkbox");
    expect(boxes.map((b) => b.closest("label")?.textContent?.trim())).toEqual(["Set reminders", "Add tasks"]);
    expect(boxes.every((b) => !(b as HTMLInputElement).checked)).toBe(true); // nothing pre-approved
    expect(screen.getByText(/Sending email and adding calendar events always ask you first/)).toBeInTheDocument();
    expect(await axeViolations(container)).toEqual([]);

    await user.click(within(group).getByRole("checkbox", { name: "Set reminders" }));
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Saved");
    expect(db.permitted).toEqual(["create_reminder"]);
  });

  it("shows what's already pre-approved, and can clear it", async () => {
    db.permitted = ["create_task"];
    const user = userEvent.setup();
    renderWithProviders(<PreApprovedActions />);
    const tasks = await screen.findByRole("checkbox", { name: "Add tasks" });
    expect(tasks).toBeChecked();
    await user.click(tasks);
    await user.click(screen.getByRole("button", { name: "Save" }));
    await screen.findByRole("status");
    expect(db.permitted).toEqual([]);
  });
});
