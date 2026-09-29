import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
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

  it("sends a suggestion chip and shows the plain reply", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ChatPage />);
    await user.click(screen.getByRole("button", { name: "what are my reminders?" }));
    expect(await screen.findByText(/\(mock\) You said/)).toBeInTheDocument();
  });
});
