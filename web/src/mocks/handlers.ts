// MSW handlers: a tiny in-browser stand-in for the API, typed from the contract.
// Used by `npm run dev:mock` (no backend at all) and by the unit tests (msw/node).
// The backend's own fakes remain the reference behaviour; keep these to the same shapes.
import { http, HttpResponse } from "msw";
import type {
  ChatEvent,
  ChatMessage,
  ChatSession,
  Delivery,
  Folder,
  HealthOut,
  Item,
  MemoryFact,
  MemorySuggestion,
  NotificationSettings,
  Proposal,
  Reminder,
  SubscriptionIn,
  Task,
  TodayOut,
  ToolInfo,
  User,
} from "../api/types";

/** A syntactically valid VAPID public key (base64url P-256 point) for the mocks. */
export const MOCK_VAPID_KEY =
  "BEl62iUYgUivxIkv69yViEuiBIa-Ib9-SkvMeAtA3LFgDzkrxZJjSgSnfckjBJuBkr3qBUYIHBQFLXYp5Nksh8U";

type Db = {
  proposals: Proposal[];
  reminders: Reminder[];
  tasks: Task[];
  folders: Folder[];
  items: Item[];
  suggestions: MemorySuggestion[];
  facts: MemoryFact[];
  settings: NotificationSettings;
  auth: { signedIn: boolean; mfaRequired: boolean; real: boolean; mfaEnabled: boolean }; // real = a non-fake auth adapter
  vapidKey: string | null;
  subscriptions: SubscriptionIn[];
  deliveries: Delivery[];
  voiceTranscript: string; // what the mock STT "hears"
  voiceUploads: string[]; // Content-Type of each uploaded recording
  spoken: string[]; // every text sent to the mock TTS
  chats: Record<string, ChatMessage[]>; // session id -> stored messages, as the API keeps them
  brief: Pick<TodayOut, "events" | "free_slots" | "unread" | "calendar_error" | "mail_error">;
};

export const db: Db = fresh();

export function resetDb() {
  Object.assign(db, fresh());
}

const newId = () => crypto.randomUUID().replaceAll("-", "");
const nowIso = () => new Date().toISOString();
const notFound = (what: string) => HttpResponse.json({ detail: `${what} not found` }, { status: 404 });

function fresh(): Db {
  const created = "2026-09-28T12:00:00Z";
  return {
    proposals: [],
    reminders: [],
    tasks: [],
    folders: [
      ...["Projects", "Areas", "Resources", "Archive"].map(
        (name): Folder => ({ id: `para-${name.toLowerCase()}`, name, kind: "para", fields: [], created_at: created }),
      ),
      {
        id: "books",
        name: "Books",
        kind: "custom",
        created_at: created,
        fields: [
          { key: "author", label: "Author", type: "text", options: null },
          { key: "status", label: "Status", type: "select", options: ["to read", "reading", "done"] },
          { key: "rating", label: "Rating", type: "rating", options: null },
        ],
      },
    ],
    items: [],
    suggestions: [],
    facts: [],
    settings: { quiet_hours: null, timezone: "America/Toronto", max_per_hour: 6, private_previews: false },
    auth: { signedIn: true, mfaRequired: true, real: false, mfaEnabled: false },
    vapidKey: MOCK_VAPID_KEY,
    subscriptions: [],
    deliveries: [],
    voiceTranscript: "what are my reminders?",
    voiceUploads: [],
    spoken: [],
    chats: {},
    brief: { events: [], free_slots: [], unread: [], calendar_error: null, mail_error: null },
  };
}

// Mirrors what pydantic emits for the backend's tool argument models.
export const TOOLS: ToolInfo[] = [
  {
    name: "create_reminder",
    description: "Create a one-off or recurring reminder, pushed to the owner's phone.",
    read_only: false,
    risk: "write",
    parameters: {
      type: "object",
      required: ["text", "due_at"],
      properties: {
        text: { type: "string", title: "Text" },
        due_at: { type: "string", format: "date-time", title: "Due At" },
        recurrence: { anyOf: [{ type: "string" }, { type: "null" }], title: "Recurrence" },
      },
    },
  },
  {
    name: "create_task",
    description: "Add a task to a horizon.",
    read_only: false,
    risk: "write",
    parameters: {
      type: "object",
      required: ["title"],
      $defs: { Horizon: { type: "string", enum: ["week", "term", "year", "someday"], title: "Horizon" } },
      properties: {
        title: { type: "string", title: "Title" },
        horizon: { $ref: "#/$defs/Horizon" },
        due_at: { anyOf: [{ type: "string", format: "date-time" }, { type: "null" }], title: "Due At" },
      },
    },
  },
  { name: "list_reminders", description: "List reminders.", read_only: true, risk: "write", parameters: { type: "object", properties: {} } },
  {
    name: "send_email",
    description: "Draft an email. It is sent only when the owner approves the card.",
    read_only: false,
    risk: "external",
    parameters: {
      type: "object",
      required: ["to", "subject", "body"],
      properties: {
        to: { type: "array", items: { type: "string" }, title: "To" },
        cc: { type: "array", items: { type: "string" }, title: "Cc" },
        subject: { type: "string", title: "Subject" },
        body: { type: "string", format: "multiline", title: "Body" },
      },
    },
  },
  {
    name: "create_event",
    description: "Add an event to the owner's calendar, warning about overlaps.",
    read_only: false,
    risk: "external",
    parameters: {
      type: "object",
      required: ["start", "end", "title"],
      properties: {
        start: { type: "string", format: "date-time", title: "Start" },
        end: { type: "string", format: "date-time", title: "End" },
        title: { type: "string", title: "Title" },
        location: { anyOf: [{ type: "string" }, { type: "null" }], title: "Location" },
      },
    },
  },
];

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

function propose(
  sessionId: string,
  tool: string,
  title: string,
  summary: string,
  args: Record<string, unknown>,
  extra: Partial<Proposal> = {},
): ChatEvent[] {
  const proposal: Proposal = {
    id: newId(),
    session_id: sessionId,
    tool,
    title,
    summary,
    args,
    preview: null,
    warnings: [],
    risk: "write",
    status: "pending",
    created_at: nowIso(),
    decided_at: null,
    result: null,
    ...extra,
  };
  db.proposals.unshift(proposal);
  return [
    { type: "tool.started", call_id: newId(), tool, args },
    { type: "proposal.created", proposal },
    ...words("I've prepared this. Approve the card to go ahead."),
    done(),
  ];
}

function reply(text: string, sessionId: string): ChatEvent[] {
  const phrase = text.trim().replace(/[.!]+$/, "");
  const reminder = /^remind me (?:to )?(.+?) in (\d+) ?(second|minute|hour)s?$/i.exec(phrase);
  if (reminder) {
    const [, what, amount, unit] = reminder;
    const seconds = Number(amount) * { second: 1, minute: 60, hour: 3600 }[unit.toLowerCase() as "second"];
    const due = new Date(Date.now() + seconds * 1000).toISOString();
    return propose(sessionId, "create_reminder", `Reminder: ${what}`, `in ${amount} ${unit}${amount === "1" ? "" : "s"}`, {
      text: what,
      due_at: due,
      recurrence: null,
    });
  }
  const task = /^add task (.+?)(?: (this week|this term|this year|someday))?$/i.exec(phrase);
  if (task) {
    const horizon = { "this week": "week", "this term": "term", "this year": "year", someday: "someday" }[
      (task[2] ?? "this week").toLowerCase() as "this week"
    ];
    return propose(sessionId, "create_task", `Task: ${task[1]}`, task[2] ?? "this week", { title: task[1], horizon, due_at: null });
  }
  const email = /^email (\S+@\S+\.\w+) (?:to say |saying |that )?(.+)$/i.exec(phrase);
  if (email) {
    const [, to, what] = email;
    const body = `Hi,\n\n${what[0].toUpperCase()}${what.slice(1)}.\n\nThanks!`;
    return propose(sessionId, "send_email", `Email to ${to}`, "Quick note", { to: [to], cc: [], subject: "Quick note", body }, {
      risk: "external",
      preview: `To: ${to}\nSubject: Quick note\n\n${body}`,
    });
  }
  const event = /^add (.+?) to my calendar tomorrow at (\d{1,2}) ?(am|pm)$/i.exec(phrase);
  if (event) {
    const [, title, hour, ampm] = event;
    const start = new Date();
    start.setDate(start.getDate() + 1);
    start.setHours((Number(hour) % 12) + (ampm.toLowerCase() === "pm" ? 12 : 0), 0, 0, 0);
    const end = new Date(start.getTime() + 3600_000);
    const clock = (d: Date) => d.toTimeString().slice(0, 5);
    return propose(
      sessionId,
      "create_event",
      `Event: ${title}`,
      `tomorrow ${clock(start)}-${clock(end)}`,
      { title, start: start.toISOString(), end: end.toISOString(), location: null },
      // the mock calendar has a standup every morning at 10, to show the conflict warning
      { risk: "external", warnings: start.getHours() === 10 ? ["Overlaps Standup, 10:00-10:30"] : [] },
    );
  }
  const remember = /^remember(?: that)? (.{3,})$/i.exec(phrase);
  if (remember) {
    db.suggestions.unshift({ id: newId(), text: remember[1], source: `chat:${sessionId}`, status: "pending", created_at: nowIso() });
    return [
      { type: "tool.result", call_id: newId(), ok: true, summary: `Memory suggestion: ${remember[1]}` },
      ...words("I'll remember that once you approve it on the Memory page."),
      done(),
    ];
  }
  return [
    ...words(
      `(mock) You said: "${text}". Try: remind me to stretch in 1 minute, email jo@example.com to say ` +
        "I'm running late, or add dentist to my calendar tomorrow at 10am.",
    ),
    done(),
  ];
}

function execute(proposal: Proposal, args: Record<string, unknown>) {
  if (proposal.tool === "send_email") return `Sent to ${(args.to as string[]).join(", ")} (mock).`;
  if (proposal.tool === "create_event") return "Added to your calendar (mock).";
  if (proposal.tool === "create_reminder") {
    db.reminders.push({
      id: newId(),
      text: String(args.text),
      due_at: String(args.due_at),
      recurrence: null,
      status: "scheduled",
      created_at: nowIso(),
      sent_at: null,
    });
    return "Reminder set (mock).";
  }
  db.tasks.push({
    id: newId(),
    title: String(args.title),
    horizon: (args.horizon as Task["horizon"]) ?? "week",
    folder_id: null,
    due_at: null,
    done: false,
    created_at: nowIso(),
  });
  return "Task added (mock).";
}

export const handlers = [
  // --- system ---
  http.get("*/api/health", () =>
    HttpResponse.json<HealthOut>({
      status: "ok",
      version: "mock",
      adapters: Object.fromEntries(
        ["agent", "llm", "embeddings", "repo", "scheduler", "auth", "mail", "calendar", "notifier", "stt", "tts"].map((seam) => [
          seam,
          { name: seam === "auth" && db.auth.real ? "totp" : "msw", fake: !(seam === "auth" && db.auth.real) },
        ]),
      ),
    }),
  ),
  http.get("*/api/tools", () => HttpResponse.json(TOOLS)),

  // --- auth ---
  http.get("*/api/me", () =>
    db.auth.signedIn
      ? HttpResponse.json<User>({ id: "owner", display_name: "Owner (mock)", mfa_enabled: db.auth.mfaEnabled })
      : HttpResponse.json({ detail: "login required" }, { status: 401 }),
  ),
  http.post<never, { username: string; password: string }>("*/api/auth/login", async ({ request }) => {
    const { password } = await request.json();
    if (password !== "correct horse") return HttpResponse.json({ detail: "invalid credentials" }, { status: 401 });
    if (db.auth.mfaRequired) return HttpResponse.json({ mfa_required: true, challenge_id: "challenge-1" });
    db.auth.signedIn = true;
    return HttpResponse.json({ mfa_required: false, challenge_id: null });
  }),
  http.post<never, { code: string }>("*/api/auth/mfa", async ({ request }) => {
    const { code } = await request.json();
    if (code !== "123456") return HttpResponse.json({ detail: "invalid code" }, { status: 401 });
    db.auth.signedIn = true;
    return new HttpResponse(null, { status: 204 });
  }),
  http.post("*/api/auth/mfa/enroll", () =>
    db.auth.real
      ? HttpResponse.json({ otpauth_uri: "otpauth://totp/HelpMate:owner?secret=MOCKSECRETKEY234&issuer=HelpMate" })
      : HttpResponse.json({ detail: "Two-step verification needs the real login" }, { status: 409 }),
  ),
  http.post<never, { code: string }>("*/api/auth/mfa/enroll/confirm", async ({ request }) => {
    if (!db.auth.real) return HttpResponse.json({ detail: "Two-step verification needs the real login" }, { status: 409 });
    if ((await request.json()).code !== "246810") {
      return HttpResponse.json({ detail: "That code doesn't match. Use the newest code." }, { status: 400 });
    }
    db.auth.mfaEnabled = true;
    return new HttpResponse(null, { status: 204 });
  }),
  http.post("*/api/auth/logout", () => {
    db.auth.signedIn = false;
    return new HttpResponse(null, { status: 204 });
  }),

  // --- chat ---
  http.post("*/api/chat/sessions", () => {
    const id = newId();
    db.chats[id] = [];
    return HttpResponse.json({ id, title: null, created_at: nowIso() }, { status: 201 });
  }),
  // like the API: chats with messages only, titled by the first one, most recent activity first
  http.get("*/api/chat/sessions", () =>
    HttpResponse.json<ChatSession[]>(
      Object.entries(db.chats)
        .filter(([, messages]) => messages.length > 0)
        .map(([id, messages]) => ({
          id,
          title: (messages.find((m) => m.role === "user") ?? messages[0]).text.slice(0, 60),
          created_at: messages[0].created_at,
          last_message_at: messages.at(-1)!.created_at,
        }))
        .sort((a, b) => Date.parse(b.last_message_at) - Date.parse(a.last_message_at)),
    ),
  ),
  http.delete<{ id: string }>("*/api/chat/sessions/:id", ({ params }) => {
    if (!db.chats[params.id]) return notFound("chat session");
    delete db.chats[params.id];
    return new HttpResponse(null, { status: 204 });
  }),
  http.get<{ id: string }>("*/api/chat/sessions/:id/messages", ({ params }) => {
    const messages = db.chats[params.id];
    return messages ? HttpResponse.json(messages) : notFound("chat session");
  }),
  http.post<{ id: string }, { text: string; source?: "text" | "voice" }>(
    "*/api/chat/sessions/:id/messages",
    async ({ params, request }) => {
      const body = await request.json();
      const messages = (db.chats[params.id] ??= []);
      const message = (role: "user" | "assistant", text: string): ChatMessage => ({
        id: newId(),
        session_id: params.id,
        role,
        text,
        source: role === "user" ? (body.source ?? "text") : "text",
        created_at: nowIso(),
      });
      messages.push(message("user", body.text));
      const events = reply(body.text, params.id);
      // like the API, the reply is stored once it's complete (here: right away)
      const text = events.map((e) => (e.type === "message.delta" ? e.text : "")).join("");
      messages.push(message("assistant", text));
      return sseFrames(events);
    },
  ),

  // --- proposals ---
  http.get("*/api/proposals", ({ request }) => {
    const status = new URL(request.url).searchParams.get("status");
    return HttpResponse.json(db.proposals.filter((p) => !status || p.status === status));
  }),
  http.get<{ id: string }>("*/api/proposals/:id", ({ params }) => {
    const proposal = db.proposals.find((p) => p.id === params.id);
    return proposal ? HttpResponse.json(proposal) : notFound("proposal");
  }),
  http.post<{ id: string }, { decision: "approve" | "reject" | "edit"; args?: Record<string, unknown> | null }>(
    "*/api/proposals/:id/decision",
    async ({ params, request }) => {
      const proposal = db.proposals.find((p) => p.id === params.id);
      if (!proposal) return notFound("proposal");
      if (proposal.status !== "pending") {
        return HttpResponse.json({ detail: `proposal is already ${proposal.status}` }, { status: 409 });
      }
      const { decision, args } = await request.json();
      if (decision === "edit" && !args) return HttpResponse.json({ detail: "an edit decision needs args" }, { status: 422 });
      proposal.decided_at = nowIso();
      if (decision === "reject") {
        proposal.status = "rejected";
      } else {
        if (decision === "edit") {
          proposal.args = args!;
          proposal.title =
            proposal.tool === "send_email"
              ? `Email to ${(args!.to as string[]).join(", ")}`
              : `${{ create_task: "Task", create_event: "Event" }[proposal.tool] ?? "Reminder"}: ${args!.title ?? args!.text}`;
        }
        proposal.result = execute(proposal, proposal.args);
        proposal.status = "executed";
      }
      return HttpResponse.json(proposal);
    },
  ),

  // --- today & reminders ---
  http.get("*/api/reminders", () => HttpResponse.json(db.reminders)),
  http.post<{ id: string }>("*/api/reminders/:id/cancel", ({ params }) => {
    const reminder = db.reminders.find((r) => r.id === params.id);
    if (!reminder) return notFound("reminder");
    reminder.status = "cancelled";
    return HttpResponse.json(reminder);
  }),
  http.get("*/api/today", () =>
    HttpResponse.json<TodayOut>({
      date: new Date().toISOString().slice(0, 10),
      timezone: "America/Toronto",
      reminders: db.reminders.filter((r) => r.status === "scheduled"),
      tasks: db.tasks.filter((t) => t.horizon === "week" && !t.done),
      pending_proposals: db.proposals.filter((p) => p.status === "pending"),
      ...db.brief,
    }),
  ),

  // --- tasks ---
  http.get("*/api/tasks", ({ request }) => {
    const horizon = new URL(request.url).searchParams.get("horizon");
    return HttpResponse.json(db.tasks.filter((t) => !horizon || t.horizon === horizon));
  }),
  http.post<never, { title: string; horizon: Task["horizon"] }>("*/api/tasks", async ({ request }) => {
    const body = await request.json();
    const task: Task = { id: newId(), title: body.title, horizon: body.horizon ?? "week", folder_id: null, due_at: null, done: false, created_at: nowIso() };
    db.tasks.push(task);
    return HttpResponse.json(task, { status: 201 });
  }),
  http.patch<{ id: string }, Partial<Task>>("*/api/tasks/:id", async ({ params, request }) => {
    const task = db.tasks.find((t) => t.id === params.id);
    if (!task) return notFound("task");
    Object.assign(task, await request.json());
    return HttpResponse.json(task);
  }),

  // --- folders & items ---
  http.get("*/api/folders", () => HttpResponse.json(db.folders)),
  http.post<never, { name: string; fields: Folder["fields"] }>("*/api/folders", async ({ request }) => {
    const body = await request.json();
    const folder: Folder = { id: newId(), name: body.name, kind: "custom", fields: body.fields ?? [], created_at: nowIso() };
    db.folders.push(folder);
    return HttpResponse.json(folder, { status: 201 });
  }),
  http.get<{ id: string }>("*/api/folders/:id/items", ({ params }) =>
    db.folders.some((f) => f.id === params.id)
      ? HttpResponse.json(db.items.filter((i) => i.folder_id === params.id))
      : notFound("folder"),
  ),
  http.post<{ id: string }, { title: string; fields: Record<string, unknown> }>(
    "*/api/folders/:id/items",
    async ({ params, request }) => {
      if (!db.folders.some((f) => f.id === params.id)) return notFound("folder");
      const body = await request.json();
      const item: Item = { id: newId(), folder_id: params.id, title: body.title, fields: body.fields, source: "manual", created_at: nowIso() };
      db.items.push(item);
      return HttpResponse.json(item, { status: 201 });
    },
  ),

  // --- memory ---
  http.get("*/api/memory/suggestions", () => HttpResponse.json(db.suggestions.filter((s) => s.status === "pending"))),
  http.post<{ id: string }, { decision: "approve" | "reject" }>(
    "*/api/memory/suggestions/:id/decision",
    async ({ params, request }) => {
      const suggestion = db.suggestions.find((s) => s.id === params.id);
      if (!suggestion) return notFound("suggestion");
      const { decision } = await request.json();
      suggestion.status = decision === "approve" ? "approved" : "rejected";
      if (decision === "approve") {
        db.facts.unshift({ id: newId(), text: suggestion.text, source: suggestion.source, created_at: nowIso() });
      }
      return HttpResponse.json(suggestion);
    },
  ),
  http.get("*/api/memory/facts", () => HttpResponse.json(db.facts)),
  http.patch<{ id: string }, { text: string }>("*/api/memory/facts/:id", async ({ params, request }) => {
    const fact = db.facts.find((f) => f.id === params.id);
    if (!fact) return notFound("fact");
    const text = (await request.json()).text.trim();
    if (!text) return HttpResponse.json({ detail: "text is empty" }, { status: 422 });
    fact.text = text;
    return HttpResponse.json(fact);
  }),
  http.delete<{ id: string }>("*/api/memory/facts/:id", ({ params }) => {
    const before = db.facts.length;
    db.facts = db.facts.filter((f) => f.id !== params.id);
    return db.facts.length < before ? new HttpResponse(null, { status: 204 }) : notFound("fact");
  }),
  http.get("*/api/export", () =>
    HttpResponse.json({
      exported_at: nowIso(),
      folders: db.folders,
      items: db.items,
      tasks: db.tasks,
      reminders: db.reminders,
      facts: db.facts,
      suggestions: db.suggestions,
      proposals: db.proposals,
      chat_sessions: [],
      chat_messages: [],
      audit: [],
    }),
  ),

  // --- settings ---
  http.post("*/api/voice/transcribe", async ({ request }) => {
    const audio = await request.arrayBuffer();
    if (!audio.byteLength) return HttpResponse.json({ detail: "empty audio" }, { status: 422 });
    db.voiceUploads.push(request.headers.get("content-type") ?? "");
    return HttpResponse.json({ text: db.voiceTranscript, language: "en", duration_ms: 1500, stt_ms: 420 });
  }),
  http.post<never, { text: string }>("*/api/voice/speak", async ({ request }) => {
    db.spoken.push((await request.json()).text);
    return new HttpResponse(new Uint8Array([82, 73, 70, 70]), { headers: { "Content-Type": "audio/wav" } }); // "RIFF"
  }),
  http.get("*/api/push/vapid-public-key", () => HttpResponse.json({ public_key: db.vapidKey })),
  http.post<never, SubscriptionIn>("*/api/push/subscriptions", async ({ request }) => {
    const subscription = await request.json();
    db.subscriptions = [...db.subscriptions.filter((s) => s.endpoint !== subscription.endpoint), subscription];
    return new HttpResponse(null, { status: 204 });
  }),
  http.delete<never, { endpoint: string }>("*/api/push/subscriptions", async ({ request }) => {
    const { endpoint } = await request.json();
    db.subscriptions = db.subscriptions.filter((s) => s.endpoint !== endpoint);
    return new HttpResponse(null, { status: 204 });
  }),
  http.post("*/api/push/test", () => {
    const id = newId();
    const now = nowIso();
    const devices = db.subscriptions.length;
    // the mock "device" acks at once, as the service worker would
    db.deliveries.unshift({ notification_id: id, kind: "test", due_at: now, sent_at: now, received_at: devices ? now : null });
    return HttpResponse.json({ notification_id: id, delivered: devices, deferred: false, detail: `${devices}/${devices} devices` });
  }),
  http.get("*/api/push/deliveries", () => HttpResponse.json(db.deliveries)),
  http.get("*/api/settings/notifications", () => HttpResponse.json(db.settings)),
  http.put<never, NotificationSettings>("*/api/settings/notifications", async ({ request }) => {
    db.settings = await request.json();
    return HttpResponse.json(db.settings);
  }),
];
