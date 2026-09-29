import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { db } from "../../mocks/handlers";
import { axeViolations, renderWithProviders } from "../../test/render";
import { TasksPage } from "./TasksPage";

describe("TasksPage", () => {
  it("adds a task to the selected horizon and ticks it off", async () => {
    const user = userEvent.setup();
    const { container } = renderWithProviders(<TasksPage />);

    await user.click(screen.getByRole("tab", { name: "This term" }));
    expect(screen.getByRole("tab", { name: "This term" })).toHaveAttribute("aria-selected", "true");
    await user.type(screen.getByLabelText("New task"), "Read chapter 3");
    await user.click(screen.getByRole("button", { name: "Add" }));

    const checkbox = await screen.findByRole("checkbox", { name: "Read chapter 3" });
    expect(db.tasks[0]).toMatchObject({ title: "Read chapter 3", horizon: "term", done: false });

    await user.click(checkbox);
    const doneHeading = await screen.findByRole("heading", { name: "Done" });
    expect(doneHeading).toBeInTheDocument();
    expect(db.tasks[0].done).toBe(true);
    expect(await axeViolations(container)).toEqual([]);
  });

  it("moves between tabs with the arrow keys", async () => {
    const user = userEvent.setup();
    renderWithProviders(<TasksPage />);
    screen.getByRole("tab", { name: "This week" }).focus();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "This term" })).toHaveFocus();
    await user.keyboard("{ArrowLeft}{ArrowLeft}");
    expect(screen.getByRole("tab", { name: "Someday" })).toHaveFocus();
  });

  it("moves a task to another horizon", async () => {
    db.tasks.push({ id: "t1", title: "Renew passport", horizon: "week", folder_id: null, due_at: null, done: false, created_at: "2026-09-29T12:00:00Z" });
    const user = userEvent.setup();
    renderWithProviders(<TasksPage />);
    const row = (await screen.findByRole("checkbox", { name: "Renew passport" })).closest("li")!;
    await user.selectOptions(within(row).getByLabelText("Move Renew passport to"), "someday");
    await screen.findByText("Nothing here yet.");
    expect(db.tasks[0].horizon).toBe("someday");
  });
});
