// MSW handlers: a tiny in-browser stand-in for the API, typed from the contract.
// Used by `npm run dev:mock` (no backend at all) and by the unit tests (msw/node).
// The backend's own fakes remain the reference behaviour; keep these to the same shapes.
import { http, HttpResponse } from "msw";
import type { ChatEvent, HealthOut, Proposal, Reminder, Task, TodayOut } from "../api/types";

type Db = { proposals: Proposal[]; reminders: Reminder[]; tasks: Task[] };

export const db: Db = fresh();

export function resetDb() {
  Object.assign(db, fresh());
}

function fresh(): Db {
  return { proposals: [], reminders: [], tasks: [] };
}

const newId = () => crypto.randomUUID().replaceAll("-", "");
const nowIso = () => new Date().toISOString();

export function sseFrames(events: ChatEvent[], gapMs = 15): HttpResponse<ReadableStream> {
  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    async start(controller) {
      for (const event of events) {
        controller.enqueue(encoder.encode(`event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`));
        if (gapMs) await new Promise((resolve) => setTimeout(resolve, gapMs));
      }
      controller.close();
    },
  });
  return new HttpResponse(stream, { headers: { "Content-Type": "text/event-stream" } });
}

const words = (text: string): ChatEvent[] =>
  (text.match(/\S+\s*/g) ?? []).map((piece) => ({ type: "message.delta", text: piece }));

const done = (): ChatEvent => ({ type: "message.done", message_id: newId(), ttft_ms: 42, tokens: 10 });

function reply(text: string, sessionId: string): ChatEvent[] {
  const reminder = /^remind me (?:to )?(.+?) in (\d+) ?(second|minute|hour)s?/i.exec(text.trim());
  if (!reminder) return [...words(`(mock) You said: "${text}". Try: remind me to stretch in 1 minute.`), done()];

  const [, what, amount, unit] = reminder;
  const seconds = Number(amount) * { second: 1, minute: 60, hour: 3600 }[unit.toLowerCase() as "second"];
  const args = { text: what, due_at: new Date(Date.now() + seconds * 1000).toISOString(), recurrence: null };
  const proposal: Proposal = {
    id: newId(),
    session_id: sessionId,
    tool: "create_reminder",
    title: `Reminder: ${what}`,
    summary: `in ${amount} ${unit}${amount === "1" ? "" : "s"}`,
    args,
    preview: null,
    risk: "write",
    status: "pending",
    created_at: nowIso(),
    decided_at: null,
    result: null,
  };
  db.proposals.unshift(proposal);
  const callId = newId();
  return [
    { type: "tool.started", call_id: callId, tool: proposal.tool, args },
    { type: "proposal.created", proposal },
    ...words("I've prepared this. Approve the card to go ahead."),
    done(),
  ];
}

export const handlers = [
  http.get("*/api/health", () =>
    HttpResponse.json<HealthOut>({
      status: "ok",
      version: "mock",
      adapters: Object.fromEntries(
        ["agent", "llm", "embeddings", "repo", "scheduler", "auth", "notifier", "stt", "tts"].map((seam) => [
          seam,
          { name: "msw", fake: true },
        ]),
      ),
    }),
  ),

  http.post("*/api/chat/sessions", () =>
    HttpResponse.json({ id: newId(), title: null, created_at: nowIso() }, { status: 201 }),
  ),

  http.post<{ id: string }, { text: string }>("*/api/chat/sessions/:id/messages", async ({ params, request }) => {
    const body = await request.json();
    return sseFrames(reply(body.text, params.id));
  }),

  http.get("*/api/proposals", ({ request }) => {
    const status = new URL(request.url).searchParams.get("status");
    return HttpResponse.json(db.proposals.filter((p) => !status || p.status === status));
  }),

  http.get<{ id: string }>("*/api/proposals/:id", ({ params }) => {
    const proposal = db.proposals.find((p) => p.id === params.id);
    return proposal ? HttpResponse.json(proposal) : HttpResponse.json({ detail: "proposal not found" }, { status: 404 });
  }),

  http.post<{ id: string }, { decision: "approve" | "reject" | "edit" }>(
    "*/api/proposals/:id/decision",
    async ({ params, request }) => {
      const proposal = db.proposals.find((p) => p.id === params.id);
      if (!proposal) return HttpResponse.json({ detail: "proposal not found" }, { status: 404 });
      if (proposal.status !== "pending") {
        return HttpResponse.json({ detail: `proposal is already ${proposal.status}` }, { status: 409 });
      }
      const { decision } = await request.json();
      proposal.decided_at = nowIso();
      if (decision === "reject") {
        proposal.status = "rejected";
      } else {
        proposal.status = "executed";
        proposal.result = "Reminder set (mock).";
        const args = proposal.args as { text: string; due_at: string };
        db.reminders.push({
          id: newId(),
          text: args.text,
          due_at: args.due_at,
          recurrence: null,
          status: "scheduled",
          created_at: nowIso(),
          sent_at: null,
        });
      }
      return HttpResponse.json(proposal);
    },
  ),

  http.get("*/api/reminders", () => HttpResponse.json(db.reminders)),

  http.post<{ id: string }>("*/api/reminders/:id/cancel", ({ params }) => {
    const reminder = db.reminders.find((r) => r.id === params.id);
    if (!reminder) return HttpResponse.json({ detail: "reminder not found" }, { status: 404 });
    reminder.status = "cancelled";
    return HttpResponse.json(reminder);
  }),

  http.get("*/api/today", () =>
    HttpResponse.json<TodayOut>({
      date: new Date().toISOString().slice(0, 10),
      timezone: "America/Toronto",
      reminders: db.reminders.filter((r) => r.status === "scheduled"),
      tasks: db.tasks,
      pending_proposals: db.proposals.filter((p) => p.status === "pending"),
    }),
  ),
];
