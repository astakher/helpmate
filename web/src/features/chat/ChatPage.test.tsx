import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { db } from "../../mocks/handlers";
import { axeViolations, renderWithProviders } from "../../test/render";
import { ChatPage } from "./ChatPage";

describe("ChatPage", () => {
  it("streams a reply, shows an approval card, and only acts after Approve", async () => {
    const user = userEvent.setup();
    const { container } = renderWithProviders(<ChatPage />);

    await user.type(screen.getByLabelText("Message"), "remind me to stretch in 1 minute{Enter}");

    const card = await screen.findByRole("article", { name: "Reminder: stretch" });
    expect(within(card).getByText("Needs your approval")).toBeInTheDocument();
    expect(db.reminders).toHaveLength(0); // nothing happens before approval

    await user.click(within(card).getByRole("button", { name: "Approve" }));
    expect(await within(card).findByRole("status")).toHaveTextContent("Done");
    expect(db.reminders.map((r) => r.text)).toEqual(["stretch"]);

    await waitFor(() => expect(screen.getByText(/Approve the card to go ahead/)).toBeInTheDocument());
    expect(await axeViolations(container)).toEqual([]);
  });

  it("shows the emails a reply found as cards, also after the app reloads", async () => {
    const user = userEvent.setup();
    const first = renderWithProviders(<ChatPage />);
    await user.type(screen.getByLabelText("Message"), "show me my emails{Enter}");

    const cards = await screen.findByRole("list", { name: "2 emails" });
    const [sam, library] = within(cards).getAllByRole("listitem");
    expect(sam).toHaveTextContent("Unread, from Sam Lee"); // the name, not "Sam Lee <sam@…>"
    expect(sam).toHaveTextContent("Quick question about Friday");
    expect(sam).toHaveTextContent("Are you still free at noon?");
    expect(library).toHaveTextContent("Your hold is ready");
    expect(library).not.toHaveTextContent("Unread");
    expect(screen.queryByText(/sam@example\.com/)).not.toBeInTheDocument(); // no raw text dump
    expect(await screen.findByText(/The newest is from Sam Lee/)).toBeInTheDocument();
    expect(await axeViolations(first.container)).toEqual([]);
    first.unmount();

    renderWithProviders(<ChatPage />); // reopening the app brings the chat back, cards included
    const restored = await screen.findByRole("list", { name: "2 emails" });
    expect(within(restored).getAllByRole("listitem")).toHaveLength(2);
  });

  it("sends a suggestion chip and shows the plain reply", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ChatPage />);
    await user.click(screen.getByRole("button", { name: "what are my reminders?" }));
    expect(await screen.findByText(/\(mock\) You said/)).toBeInTheDocument();
  });

  describe("when scrollIntoView returns a Promise (current Chrome)", () => {
    afterEach(() => {
      delete (Element.prototype as Partial<Element>).scrollIntoView;
    });

    it("keeps rendering as turns change and on unmount", async () => {
      // jsdom has no scrollIntoView; Chrome's returns a Promise, which must not become the effect cleanup.
      Element.prototype.scrollIntoView = vi.fn(() => Promise.resolve()) as unknown as Element["scrollIntoView"];
      const user = userEvent.setup();
      const { unmount } = renderWithProviders(<ChatPage />);
      await user.click(screen.getByRole("button", { name: "what are my reminders?" }));
      expect(await screen.findByText(/\(mock\) You said/)).toBeInTheDocument();
      expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
      expect(() => unmount()).not.toThrow();
    });
  });
});
