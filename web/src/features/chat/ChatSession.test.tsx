import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NavLink, Route, Routes } from "react-router";
import { describe, expect, it } from "vitest";
import type { ChatMessage } from "../../api/types";
import { db } from "../../mocks/handlers";
import { renderWithProviders } from "../../test/render";
import { ChatPage } from "./ChatPage";
import { SESSION_KEY } from "./useChat";

/** The chat page plus one other page, like the app's routes (the provider sits above both). */
function TwoPages() {
  return (
    <>
      <nav>
        <NavLink to="/">Chat</NavLink>
        <NavLink to="/memory">Memory</NavLink>
      </nav>
      <Routes>
        <Route path="/" element={<ChatPage />} />
        <Route path="/memory" element={<p>Memory page</p>} />
      </Routes>
    </>
  );
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

function stored(sessionId: string, role: ChatMessage["role"], text: string, at: string): ChatMessage {
  return { id: `${role}-${at}`, session_id: sessionId, role, text, source: "text", created_at: at };
}

describe("the conversation outlives the chat page", () => {
  it("is still there after going to another page and back", async () => {
    const user = userEvent.setup();
    renderWithProviders(<TwoPages />);
    await user.type(screen.getByLabelText("Message"), "add task read chapter 3 this term{Enter}");
    expect(await screen.findByRole("article", { name: "Task: read chapter 3" })).toBeInTheDocument();
    await screen.findByText(/Approve the card to go ahead/);

    await user.click(screen.getByRole("link", { name: "Memory" }));
    expect(screen.getByText("Memory page")).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: "Chat" }));

    expect(screen.getByText("add task read chapter 3 this term")).toBeInTheDocument();
    expect(screen.getByRole("article", { name: "Task: read chapter 3" })).toBeInTheDocument();
  });

  it("keeps streaming a reply while you're on another page", async () => {
    const user = userEvent.setup();
    renderWithProviders(<TwoPages />);
    await user.type(screen.getByLabelText("Message"), "remind me to stretch in 1 minute{Enter}");
    await user.click(screen.getByRole("link", { name: "Memory" })); // leave mid-reply
    await sleep(600); // the mock streams a word every 15 ms

    await user.click(screen.getByRole("link", { name: "Chat" }));
    expect(screen.getByText(/Approve the card to go ahead/)).toBeInTheDocument(); // already complete
    expect(screen.queryByText("HelpMate is typing")).not.toBeInTheDocument();
    expect(screen.getByRole("article", { name: "Reminder: stretch" })).toBeInTheDocument();
  });

  it("comes back after a reload, with its approval cards, and carries on in the same session", async () => {
    db.chats.s1 = [
      stored("s1", "user", "remind me to stretch in 1 minute", "2026-10-01T12:00:00Z"),
      stored("s1", "assistant", "I've prepared this. Approve the card to go ahead.", "2026-10-01T12:00:02Z"),
    ];
    db.proposals.push({
      id: "p1",
      session_id: "s1",
      tool: "create_reminder",
      title: "Reminder: stretch",
      summary: "in 1 minute",
      args: { text: "stretch", due_at: "2026-10-01T12:01:00Z", recurrence: null },
      preview: null,
      warnings: [],
      risk: "write",
      status: "pending",
      created_at: "2026-10-01T12:00:01Z",
      decided_at: null,
      result: null,
    });
    localStorage.setItem(SESSION_KEY, "s1");
    const user = userEvent.setup();
    renderWithProviders(<ChatPage />);

    expect(await screen.findByText("remind me to stretch in 1 minute")).toBeInTheDocument();
    const card = screen.getByRole("article", { name: "Reminder: stretch" });
    expect(within(card).getByRole("button", { name: "Approve" })).toBeInTheDocument();

    await user.type(screen.getByLabelText("Message"), "hello again{Enter}");
    await waitFor(() => expect(db.chats.s1.map((m) => m.text)).toContain("hello again"));
    expect(Object.keys(db.chats)).toEqual(["s1"]); // no new session
  });

  it("starts fresh when the stored session no longer exists", async () => {
    localStorage.setItem(SESSION_KEY, "gone");
    renderWithProviders(<ChatPage />);
    expect(await screen.findByRole("button", { name: "what are my reminders?" })).toBeInTheDocument();
    expect(localStorage.getItem(SESSION_KEY)).toBeNull();
  });

  it("New chat clears the conversation and the next message opens a new session", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ChatPage />);
    await user.click(screen.getByRole("button", { name: "what are my reminders?" }));
    await screen.findByText(/\(mock\) You said/);
    const first = localStorage.getItem(SESSION_KEY);
    expect(first).not.toBeNull();

    await user.click(screen.getByRole("button", { name: "New chat" }));
    expect(screen.queryByText(/\(mock\) You said/)).not.toBeInTheDocument();
    expect(localStorage.getItem(SESSION_KEY)).toBeNull();

    await user.type(screen.getByLabelText("Message"), "hi{Enter}");
    await screen.findByText(/\(mock\) You said: "hi"/);
    expect(localStorage.getItem(SESSION_KEY)).not.toBe(first);
    expect(Object.keys(db.chats)).toHaveLength(2);
  });
});
