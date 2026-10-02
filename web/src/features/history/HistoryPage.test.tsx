import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { AuditEntry } from "../../api/types";
import { db } from "../../mocks/handlers";
import { axeViolations, renderWithProviders } from "../../test/render";
import { HistoryPage } from "./HistoryPage";

let n = 0;
const entry = (actor: AuditEntry["actor"], action: string, detail: AuditEntry["detail"], target = "p1"): AuditEntry => ({
  id: `a${++n}`,
  at: new Date(Date.now() - n * 60_000).toISOString(),
  actor,
  action,
  target,
  detail,
});

describe("HistoryPage", () => {
  it("tells what happened in plain words, and confirms every change was approved", async () => {
    db.audit = [
      entry("agent", "tool.executed", { tool: "create_task", title: "Task: read ch. 3", pre_approved: true }, "create_task"),
      entry("agent", "tool.executed", { tool: "search_email", read_only: true }, "search_email"),
      entry("system", "tool.executed", { tool: "create_reminder", title: "Reminder: stretch" }),
      entry("user", "proposal.approved", { tool: "create_reminder", title: "Reminder: stretch" }),
      entry("agent", "proposal.created", { tool: "create_reminder", title: "Reminder: stretch" }),
      entry("user", "proposal.rejected", { tool: "send_email", title: "Email to jo@example.com" }, "p2"),
    ];
    const user = userEvent.setup();
    const { container } = renderWithProviders(<HistoryPage />);

    const today = await screen.findByRole("region", { name: "Today" });
    const rows = within(today)
      .getAllByRole("listitem")
      .map((li) => li.querySelector("span")?.textContent);
    expect(rows).toEqual([
      "Done without asking (you pre-approved it): Task: read ch. 3",
      "Done: Reminder: stretch",
      "You approved: Reminder: stretch",
      "HelpMate asked to: Reminder: stretch",
      "You declined: Email to jo@example.com",
    ]); // the email search is a lookup: hidden until asked for
    expect(screen.getByRole("status")).toHaveTextContent("2 changes below, each one approved by you or pre-approved.");
    expect(await axeViolations(container)).toEqual([]);

    await user.click(screen.getByRole("checkbox", { name: /Also show lookups/ }));
    expect(within(today).getByText("HelpMate searched your email")).toBeInTheDocument();
  });

  it("flags a change with no approval on record", async () => {
    db.audit = [entry("agent", "tool.executed", { tool: "create_task", title: "Task: mystery" }, "create_task")];
    renderWithProviders(<HistoryPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("1 change ran without an approval record");
    expect(screen.getByText(/no approval on record/)).toBeInTheDocument();
  });
});
