# API contract

`contracts/openapi.yaml` is the single source of truth between the web app (C) and the backend (A + B).

## How it's produced
1. Request/response models live in `backend/src/helpmate/api/schemas/` (pydantic).
2. `uv run python ../scripts/export_openapi.py` (run from `backend/`) writes `contracts/openapi.yaml`.
3. `npm run gen:api` (from `web/`) turns it into `web/src/api/schema.d.ts`. The typed client (`openapi-fetch`) and the MSW mocks use those types.
4. CI regenerates both files and fails if either differs from what's committed, so every contract change shows up in the PR diff.

## Chat stream events
OpenAPI can't describe the events inside an SSE stream, so `ChatEvent` is a pydantic discriminated union (keyed on `type`) that is also published as a named schema component. Each SSE frame is:

```
event: <type>
data: <ChatEvent JSON>
```

| `type` | Payload | Who emits |
|---|---|---|
| `message.delta` | `{text}` | agent (streamed tokens) |
| `tool.started` | `{call_id, tool, args}` | agent |
| `tool.result` | `{call_id, ok, summary}` | agent |
| `proposal.created` | `{proposal: Proposal}` | policy engine |
| `message.done` | `{message_id, ttft_ms, tokens}` | agent |
| `error` | `{code, message}` | any |

The server sends a `: ping` comment every 15 s so proxies (Tailscale) keep the stream open.

## Voice upload
`POST /api/voice/transcribe` takes the recording as a **raw request body** (`Content-Type: audio/webm;codecs=opus`, `audio/mp4`, …), not multipart form data. Starlette spools multipart files larger than 1 MB to a temp file on disk, whereas a raw body stays in memory and is dropped after transcription. That's how the "recordings are never stored" promise holds.

## Push payload (backend → service worker)
`WebPushNotifier` sends JSON `{id, kind, title, body, url, tag}`. `web/src/sw.ts` shows it and POSTs `/api/push/ack {notification_id: id, received_at}`, so `received_at - due_at` is the delivery latency.

## Change rules
- Additive changes (a new endpoint, optional field or event type) are fine with the normal review, but mention them in the PR.
- Breaking changes (rename, remove, type change, required field) need all three members to agree first, and they stop being allowed after week 2.
- CODEOWNERS enforces three-way review on `contracts/`, `domain/` and `api/schemas/`.
