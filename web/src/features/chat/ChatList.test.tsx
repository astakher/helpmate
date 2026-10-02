import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { ChatMessage } from "../../api/types";
import { db } from "../../mocks/handlers";
import { axeViolations, renderWithProviders } from "../../test/render";
import { ChatPage } from "./ChatPage";
import { SESSION_KEY } from "./useChat";

function message(sessionId: string, role: ChatMessage["role"], text: string, at: string): ChatMessage {
  return { id: `${sessionId}-${role}`, session_id: sessionId, role, text, source: "text", created_at: at, emails: [] };
}

function seedTwoChats() {
  db.chats.older = [
    message("older", "user", "first chat question", "2026-09-29T10:00:00Z"),
    message("older", "assistant", "answer one", "2026-09-29T10:00:02Z"),
  ];
  db.chats.newer = [
    message("newer", "user", "second chat question", "2026-09-30T10:00:00Z"),
    message("newer", "assistant", "answer two", "2026-09-30T10:00:02Z"),
  ];
}

const chatList = () => screen.getByRole("navigation", { name: "Chats" });
const log = () => screen.getByRole("log");

describe("the chat list", () => {
  it("lists chats newest first and opens the one you pick", async () => {
    seedTwoChats();
    const user = userEvent.setup();
    const { container } = renderWithProviders(<ChatPage />);

    const titles = await within(chatList()).findAllByRole("button", { name: /^(first|second) chat question/ });
    expect(titles.map((b) => b.textContent)).toEqual([
      expect.stringContaining("second chat question"),
      expect.stringContaining("first chat question"),
    ]);
    expect(await axeViolations(container)).toEqual([]);

    await user.click(within(chatList()).getByRole("button", { name: /^first chat question/ }));
    expect(await within(log()).findByText("answer one")).toBeInTheDocument();
    expect(within(chatList()).getByRole("button", { name: /^first chat question/ })).toHaveAttribute(
      "aria-current",
      "true",
    );

    await user.click(within(chatList()).getByRole("button", { name: /^second chat question/ }));
    expect(await within(log()).findByText("answer two")).toBeInTheDocument();
    expect(within(log()).queryByText("answer one")).not.toBeInTheDocument();
    expect(localStorage.getItem(SESSION_KEY)).toBe("newer"); // a reload reopens this one
  });

  it("adds a new conversation to the list once it has a message", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ChatPage />);
    expect(await within(chatList()).findByText(/No chats yet/)).toBeInTheDocument();
    await user.type(screen.getByRole("textbox", { name: "Message" }), "hello there{Enter}");
    expect(await within(chatList()).findByRole("button", { name: /^hello there/ })).toHaveAttribute(
      "aria-current",
      "true",
    );
  });

  it("deletes a chat only after you confirm", async () => {
    seedTwoChats();
    const user = userEvent.setup();
    renderWithProviders(<ChatPage />);
    await within(chatList()).findByRole("button", { name: /^first chat question/ });

    await user.click(screen.getByRole("button", { name: "Delete chat “first chat question”" }));
    const confirm = screen.getByRole("group", { name: "Delete “first chat question”?" });
    await user.click(within(confirm).getByRole("button", { name: "Cancel" }));
    expect(db.chats.older).toBeDefined();

    await user.click(screen.getByRole("button", { name: "Delete chat “first chat question”" }));
    await user.click(within(screen.getByRole("group")).getByRole("button", { name: "Delete" }));
    await waitFor(() =>
      expect(within(chatList()).queryByRole("button", { name: /^first chat question/ })).not.toBeInTheDocument(),
    );
    expect(db.chats.older).toBeUndefined();
    expect(within(chatList()).getByRole("button", { name: /^second chat question/ })).toBeInTheDocument();
  });

  it("deleting the open chat starts a new one", async () => {
    seedTwoChats();
    localStorage.setItem(SESSION_KEY, "newer");
    const user = userEvent.setup();
    renderWithProviders(<ChatPage />);
    expect(await within(log()).findByText("answer two")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Delete chat “second chat question”" }));
    await user.click(within(screen.getByRole("group")).getByRole("button", { name: "Delete" }));
    expect(await screen.findByRole("button", { name: "what are my reminders?" })).toBeInTheDocument();
    expect(within(log()).queryByText("answer two")).not.toBeInTheDocument();
    expect(localStorage.getItem(SESSION_KEY)).toBeNull();
  });

  it("folds away behind a Chats button on phones", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ChatPage />);
    const toggle = screen.getByRole("button", { name: "Chats" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveAttribute("aria-controls", "chat-list");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
  });
});
