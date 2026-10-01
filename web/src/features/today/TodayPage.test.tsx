import { screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { HealthOut } from "../../api/types";
import { db } from "../../mocks/handlers";
import { server } from "../../mocks/node";
import { axeViolations, renderWithProviders } from "../../test/render";
import { TodayPage } from "./TodayPage";

const minutes = (n: number) => new Date(Date.now() + n * 60_000).toISOString();
const card = (name: string) => screen.getByRole("region", { name });

function midnight(dayOffset = 0): string {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  d.setDate(d.getDate() + dayOffset);
  return d.toISOString();
}

function useGmail() {
  server.use(
    http.get("*/api/health", () =>
      HttpResponse.json<HealthOut>({
        status: "ok",
        version: "test",
        adapters: { mail: { name: "gmail", fake: false }, calendar: { name: "google", fake: false } },
      }),
    ),
  );
}

describe("the daily brief", () => {
  it("shows today's schedule, the free time left and unread mail", async () => {
    db.brief = {
      events: [
        { id: "e1", title: "Standup", start: minutes(-90), end: minutes(-60), location: null, description: null },
        { id: "e2", title: "Lab", start: minutes(-15), end: minutes(45), location: "ITB 137", description: null },
        { id: "e3", title: "Thanksgiving", start: midnight(), end: midnight(1), location: null, description: null },
      ],
      free_slots: [{ start: minutes(60), end: minutes(150) }],
      unread: [
        {
          id: "m1",
          sender: "Sam Lee <sam@example.com>",
          subject: "Notes from Tuesday",
          snippet: "",
          received_at: minutes(-5),
          unread: true,
        },
      ],
      calendar_error: null,
      mail_error: null,
    };
    useGmail();
    const { container } = renderWithProviders(<TodayPage />);

    const schedule = await screen.findByRole("region", { name: "Schedule" });
    const rows = await within(schedule).findAllByRole("listitem");
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringContaining("All day"), // all-day events first
      expect.stringContaining("Standup"),
      expect.stringContaining("Lab"),
    ]);
    expect(rows[1]).toHaveTextContent("(finished)");
    expect(within(rows[2]).getByText("Now")).toBeInTheDocument();
    expect(rows[2]).toHaveTextContent("ITB 137");

    expect(within(card("Free time left today")).getByText("1 h 30 min")).toBeInTheDocument();

    const mail = card("Unread mail");
    expect(within(mail).getByText("Sam Lee")).toBeInTheDocument(); // the name, not the address
    expect(await within(mail).findByRole("link", { name: /^Notes from Tuesday/ })).toHaveAttribute(
      "href",
      "https://mail.google.com/mail/u/0/#inbox/m1",
    );
    expect(await axeViolations(container)).toEqual([]);
  });

  it("explains a section Google couldn't answer and still shows the rest", async () => {
    db.brief = {
      events: [],
      free_slots: [],
      unread: [],
      calendar_error: "Google's sign-in expired. Run google_auth.py",
      mail_error: null,
    };
    renderWithProviders(<TodayPage />);
    const schedule = await screen.findByRole("region", { name: "Schedule" });
    expect(await within(schedule).findByRole("alert")).toHaveTextContent("sign-in expired");
    expect(within(card("Free time left today")).getByText(/Needs your calendar/)).toBeInTheDocument();
    expect(within(card("Unread mail")).getByText("No unread mail.")).toBeInTheDocument();
  });

  it("says so when the calendar isn't connected, and links nothing to Gmail on the fakes", async () => {
    db.brief.unread = [
      { id: "m1", sender: "x@example.com", subject: "Hi", snippet: "", received_at: minutes(-5), unread: true },
    ];
    renderWithProviders(<TodayPage />);
    expect(await screen.findByText(/Google Calendar isn't connected/)).toBeInTheDocument();
    expect(within(card("Unread mail")).getByText("x@example.com")).toBeInTheDocument();
    expect(within(card("Unread mail")).queryByRole("link")).not.toBeInTheDocument();
  });
});
