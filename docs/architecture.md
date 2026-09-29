# Architecture

![Architecture](img/architecture.png)

## Planes
- **Core plane** (always needed; could later move to a low-power mini PC): FastAPI API, agent loop, policy engine, scheduler/worker, PostgreSQL + pgvector, SeaweedFS.
- **Inference plane** (GPU laptop): Ollama (chat model + embeddings) and the speech service (faster-whisper + Kokoro on CPU). The core reaches both over HTTP on `127.0.0.1` (or over the tailnet if the planes are split across machines).
- **Edge:** Tailscale Serve/Funnel terminates TLS on the laptop and forwards to FastAPI. Nothing else is reachable from outside.

## Request lifecycles

**Text chat**
1. The web app sends `POST /api/chat/sessions/{id}/messages {text}`, and the response is a `text/event-stream`.
2. The router calls `AgentPort.run()`, which yields `ChatEvent`s: `message.delta`, `tool.started`, `tool.result`, `proposal.created`, `message.done`.
3. Read-only tools run straight away. Write tools do not run; the policy engine turns them into a **Proposal**.
4. The web app renders the proposal as a card. The user sends `POST /api/proposals/{id}/decision` → the tool executes → the audit log records it.

**Voice**: push-to-talk in the browser (MediaRecorder) → `POST /api/voice/transcribe` → the core's `STTPort` → the speech service (faster-whisper). The transcript then enters the text chat flow with `source: voice`. The reply is spoken via `POST /api/voice/speak` (Kokoro), one sentence at a time. Audio stays in memory and is never written to disk.

**Reminder**: an approved `create_reminder` → the scheduler enqueues a job → at the due time the worker calls `NotifierPort.notify()` → `QuietHoursNotifier` → `WebPushNotifier` → the browser's push service → the service worker shows the notification and POSTs `/api/push/ack`. The ack timestamp minus the due time is the delivery latency (target: 95% within 60 s).

## Hexagonal boundaries
- `domain/` has no framework imports. It holds models (pydantic) and ports (Protocols).
- `adapters/` holds the implementations of the ports. Each one is selected in `container.py` from settings.
- `api/` holds FastAPI routers. They depend on ports only, never on concrete adapters.
- Each port has a contract test suite in `backend/tests/contracts/` that runs against the fake and against every real adapter.

## Security and privacy boundaries
- Ollama, the speech service, Postgres and SeaweedFS bind to `127.0.0.1` only.
- The only outbound traffic is approved Gmail/Calendar actions and Web Push. Push payloads are encrypted end to end (RFC 8291), and `private_previews` keeps personal text out of them.
- Session cookies are HttpOnly and `SameSite=Strict`, served from a single origin (the web app and `/api` on one host).
