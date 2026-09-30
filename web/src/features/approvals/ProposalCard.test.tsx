import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { Proposal } from "../../api/types";
import { db } from "../../mocks/handlers";
import { axeViolations, renderWithProviders } from "../../test/render";
import { ProposalCard } from "./ProposalCard";

function proposal(overrides: Partial<Proposal> = {}): Proposal {
  return {
    id: "p1",
    session_id: null,
    tool: "create_reminder",
    title: "Reminder: call mom",
    summary: "Mon Oct 05 at 17:00",
    args: { text: "call mom", due_at: "2026-10-05T21:00:00Z" },
    preview: null,
    risk: "write",
    status: "pending",
    created_at: "2026-10-05T16:00:00Z",
    decided_at: null,
    result: null,
    ...overrides,
  };
}

describe("ProposalCard", () => {
  it("cancelling executes nothing", async () => {
    db.proposals.push(proposal());
    renderWithProviders(<ProposalCard proposal={proposal()} />);
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Cancelled");
    expect(db.reminders).toHaveLength(0);
  });

  it("refreshes itself when the proposal was already decided elsewhere (409)", async () => {
    db.proposals.push(proposal({ status: "rejected" }));
    renderWithProviders(<ProposalCard proposal={proposal()} />); // stale prop still says pending
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Cancelled");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("flags actions that leave the device and shows the full preview", async () => {
    const { container } = renderWithProviders(
      <ProposalCard proposal={proposal({ risk: "external", tool: "send_email", preview: "Hi Prof,\n..." })} />,
    );
    expect(screen.getByText(/Leaves this device/)).toBeInTheDocument();
    expect(screen.getByLabelText("Full preview")).toHaveTextContent("Hi Prof,");
    expect(await axeViolations(container)).toEqual([]);
  });

  it("shows conflict warnings while the card is pending, and not once it's decided", async () => {
    const event = proposal({
      tool: "create_event",
      title: "Event: dentist",
      risk: "external",
      warnings: ["Overlaps Standup, Tue Oct 06 10:00-11:00"],
    });
    db.proposals.push({ ...event });
    const { container } = renderWithProviders(<ProposalCard proposal={event} />);
    expect(screen.getByRole("list", { name: "Before you approve" })).toHaveTextContent("Overlaps Standup");
    expect(await axeViolations(container)).toEqual([]);

    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Done");
    expect(screen.queryByRole("list", { name: "Before you approve" })).not.toBeInTheDocument();
  });
});
