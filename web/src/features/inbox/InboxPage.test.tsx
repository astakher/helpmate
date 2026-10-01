import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { TriagedEmail } from "../../api/types";
import { db } from "../../mocks/handlers";
import { axeViolations, renderWithProviders } from "../../test/render";
import { InboxPage } from "./InboxPage";

function item(id: string, category: TriagedEmail["category"], extra: Partial<TriagedEmail> = {}): TriagedEmail {
  return {
    email: {
      id,
      sender: "Sam Lee <sam@example.com>",
      subject: `Subject ${id}`,
      snippet: "",
      received_at: new Date().toISOString(),
      unread: true,
      labels: [],
    },
    category,
    reason: `Reason for ${id}`,
    suspicious: false,
    sorted_by: "model",
    ...extra,
  };
}

describe("the inbox", () => {
  it("groups unread mail and warns about emails that address an AI", async () => {
    db.inbox.items = [
      item("a", "reply", { suspicious: true }),
      item("b", "fyi"),
      item("c", "low", { sorted_by: "rules" }),
    ];
    const { container } = renderWithProviders(<InboxPage />);
    const reply = await screen.findByRole("region", { name: /Needs a reply/ });
    expect(within(reply).getByText("Subject a")).toBeInTheDocument();
    expect(within(reply).getByText("Sam Lee")).toBeInTheDocument();
    expect(within(reply).getByRole("note")).toHaveTextContent("text aimed at an AI assistant");
    expect(within(screen.getByRole("region", { name: /For your information/ })).getByText("Subject b")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: /Low priority/ })).getByText("Reason for c")).toBeInTheDocument();
    // only mail that needs a reply offers one
    expect(screen.getAllByRole("button", { name: /^Draft a reply/ })).toHaveLength(1);
    expect(await axeViolations(container)).toEqual([]);
  });

  it("drafts a reply as an approval card addressed to the sender", async () => {
    db.inbox.items = [item("a", "reply")];
    const user = userEvent.setup();
    renderWithProviders(<InboxPage />);
    await user.click(await screen.findByRole("button", { name: "Draft a reply to Sam Lee: Subject a" }));
    const card = await screen.findByRole("article", { name: "Email to sam@example.com" });
    expect(within(card).getByLabelText("Full preview")).toHaveTextContent("Subject: Re: Subject a");
    expect(within(card).getByRole("button", { name: "Approve" })).toBeInTheDocument();
  });

  it("explains when the mailbox can't be read", async () => {
    db.inbox = { items: [], error: "Google's sign-in expired." };
    renderWithProviders(<InboxPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("sign-in expired");
  });
});
