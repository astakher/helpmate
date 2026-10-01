import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { DayPlan, Task } from "../../api/types";
import { db } from "../../mocks/handlers";
import { axeViolations, renderWithProviders } from "../../test/render";
import { WeekPage } from "./WeekPage";

function isoDay(offset: number): string {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

const at = (offset: number, hour: number, minute = 0) => {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  d.setHours(hour, minute, 0, 0);
  return d.toISOString();
};

function emptyDay(offset: number): DayPlan {
  return { date: isoDay(offset), events: [], free_slots: [], reminders: [], tasks_due: [] };
}

const task = (title: string, extra: Partial<Task> = {}): Task => ({
  id: `t-${title}`,
  title,
  horizon: "week",
  folder_id: null,
  due_at: null,
  done: false,
  created_at: "2026-10-01T12:00:00Z",
  ...extra,
});

describe("the week plan", () => {
  it("shows each day's events, free time, reminders and tasks due", async () => {
    db.week.days = Array.from({ length: 7 }, (_, i) => emptyDay(i));
    db.week.days[0].events = [
      { id: "e1", title: "Lab", start: at(0, 13), end: at(0, 15), location: "ITB 137", description: null },
    ];
    db.week.days[0].free_slots = [{ start: at(0, 15), end: at(0, 18) }];
    db.week.days[1].reminders = [
      { id: "r1", text: "pay rent", due_at: at(1, 9), recurrence: null, status: "scheduled", created_at: at(0, 8), sent_at: null },
    ];
    db.week.days[2].tasks_due = [task("essay draft", { due_at: at(2, 17) })];
    const { container } = renderWithProviders(<WeekPage />);

    const today = await screen.findByRole("region", { name: /^Today/ });
    expect(within(today).getByText("Lab")).toBeInTheDocument();
    expect(within(today).getByText(/Free 3 h:/)).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: /^Tomorrow/ })).getByText("pay rent")).toBeInTheDocument();
    expect(screen.getByText("essay draft")).toBeInTheDocument();
    expect(screen.getAllByText("Nothing booked.")).toHaveLength(4);
    expect(await axeViolations(container)).toEqual([]);
  });

  it("finds an hour for an undated task as an approval card", async () => {
    db.tasks.push(task("read chapter 3"));
    const user = userEvent.setup();
    renderWithProviders(<WeekPage />);
    const fit = await screen.findByRole("region", { name: "To fit in this week" });
    await user.click(within(fit).getByRole("button", { name: "Find an hour for read chapter 3" }));

    const card = await within(fit).findByRole("article", { name: "Event: read chapter 3" });
    expect(within(card).getByText(/Leaves this device/)).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Approve" })).toBeInTheDocument();
    expect(db.proposals[0].tool).toBe("create_event"); // a card, not an event yet
  });

  it("says when no hour is free, and when the calendar can't be read", async () => {
    db.tasks.push(task("read chapter 3"));
    db.week.full = true;
    db.week.calendar_error = "Google's sign-in expired.";
    const user = userEvent.setup();
    renderWithProviders(<WeekPage />);
    expect((await screen.findAllByRole("alert"))[0]).toHaveTextContent("sign-in expired");
    await user.click(screen.getByRole("button", { name: "Find an hour for read chapter 3" }));
    expect(await screen.findByText(/No free 60 minutes/)).toBeInTheDocument();
  });
});
