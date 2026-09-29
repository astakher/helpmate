import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { Proposal } from "../../api/types";
import { db, TOOLS } from "../../mocks/handlers";
import { axeViolations, renderWithProviders } from "../../test/render";
import { ProposalCard } from "./ProposalCard";
import { schemaFields } from "./schemaFields";

const task: Proposal = {
  id: "p-task",
  session_id: null,
  tool: "create_task",
  title: "Task: read chapter 3",
  summary: "this term",
  args: { title: "read chapter 3", horizon: "term", due_at: null },
  preview: null,
  risk: "write",
  status: "pending",
  created_at: "2026-09-29T12:00:00Z",
  decided_at: null,
  result: null,
};

describe("schemaFields", () => {
  it("reads pydantic-style schemas: $ref enums, Optional and date-time", () => {
    const fields = schemaFields(TOOLS[1].parameters);
    expect(fields).toEqual([
      { name: "title", label: "Title", kind: "text", required: true },
      { name: "horizon", label: "Horizon", kind: "enum", options: ["week", "term", "year", "someday"], required: false },
      { name: "due_at", label: "Due At", kind: "datetime", required: false },
    ]);
  });
});

describe("Edit then approve", () => {
  it("executes the edited arguments, not the original ones", async () => {
    db.proposals.push({ ...task });
    const user = userEvent.setup();
    const { container } = renderWithProviders(<ProposalCard proposal={task} />);

    await user.click(await screen.findByRole("button", { name: "Edit" }));
    const title = screen.getByLabelText("Title");
    await user.clear(title);
    await user.type(title, "read chapter 4");
    await user.selectOptions(screen.getByLabelText("Horizon"), "week");
    expect(await axeViolations(container)).toEqual([]);
    await user.click(screen.getByRole("button", { name: "Save and approve" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Done");
    expect(db.tasks.map((t) => [t.title, t.horizon])).toEqual([["read chapter 4", "week"]]);
  });
});
