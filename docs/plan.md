# HelpMate — Build Plan

> Living plan for the whole team. Workstream C (Aman Takher) wrote the week-1 version: repo, contract, walking skeleton.

## Context

Group project for ENG TECH 4FD3 (McMaster, Fall 2026). HelpMate is a local-first agentic assistant: an LLM (Ollama) runs on the owner's laptop, turns requests into typed tool calls, and every write the agent wants to make becomes an approval card. The docs are two specs that conflict, plus the course outline:

- **Original spec**: 3 members. A = agent/LLM/memory/eval, B = backend/data/integrations/security/deploy, **C = Aman: web app (React PWA), voice (faster-whisper + Kokoro), notifications (Web Push)**. It also makes C the lead for project **week 1** (repo, CI, API contract, walking skeleton, model benchmark), **week 4** (push-to-talk, reminders pushed to the phone, custom folders, secure public deploy) and **week 6** (E2E + DST tests, demo).
- **Updated spec**: lists only Jaskaran + Pratham. It drops voice/PWA/push and adds Google Calendar, a Llama-family model, a 13-week timeline and network-monitoring validation.

**Decisions:** merge both specs. The repo lives on Aman's GitHub. Development runs on a **Dell XPS 15** (Win 11, i7-8750H, 16 GB RAM, GTX 1050 Ti Max-Q **4 GB VRAM**). The demo host (the spec's RTX 4070 laptop?) is not decided yet, so we benchmark on the XPS now and re-run the benchmark on the demo host later.

**The goal:** a walking skeleton where every part works end to end on day 1 using *fakes*. Each teammate's real implementation then replaces a fake behind a fixed interface, so Aman's UI, voice and notifications just work when A and B finish.

**Flags for the team:**
1. The Updated spec's team list leaves Aman out. Fix that before it's submitted.
2. Gmail access (B): the original spec says SMTP/IMAP with an app password, but the Updated spec says "credentials will not be stored directly". OAuth with minimal scopes for Gmail and Google Calendar satisfies both. B decides.
3. Record in the specs that Jaskaran and Pratham map to workstreams A and B (the original spec leaves placeholders).

**How we execute:** Phases 0–2 need no GPU and use fakes everywhere, so they run on any machine. Phases 3, 5 (real models) and 7 need the GPU host; the setup commands are in `docs/setup-windows.md`.

---

## 1. How the whole system works (mental model)

```
Phone/desktop browser (PWA)  ──HTTPS (Tailscale)──►  FastAPI core (laptop)
  React UI  ◄── SSE stream ──  /api/chat ─► AgentPort (A) ─► LLMPort ─► Ollama (GPU)
  mic ─► /api/voice/transcribe ─► STTPort ─► speech service (faster-whisper, CPU)
  speaker ◄─ /api/voice/speak ◄─ TTSPort ◄─ speech service (Kokoro, CPU)
  approval card ─► /api/proposals/{id}/decision ─► PolicyEngine (A) ─► tool executes (A/B) ─► audit log (B)
  service worker ◄── Web Push ◄── NotifierPort (C) ◄── scheduler/job queue (B) ◄── reminders in Postgres (B)
```

- **Text request:** UI POSTs the message → the agent asks the LLM which tool to call → read-only tools run straight away → a write tool produces a `proposal` event → the UI shows a card → the user taps Approve → the tool runs and the action is logged.
- **Voice request:** push-to-talk records audio (never written to disk) → transcribed to text → goes through the same chat flow → the reply is spoken sentence by sentence.
- **Reminder:** an approved `create_reminder` → a job row in Postgres → the worker fires at the due time → `NotifierPort.notify()` → Web Push → the phone's service worker shows it and POSTs a delivery ack (this is how the 60-second target gets measured).
- **Privacy boundary:** Ollama, speech, Postgres and SeaweedFS bind to `127.0.0.1` only. The only public entry point is Tailscale → FastAPI. The only outbound traffic is approved Gmail/Calendar actions and Web Push.

## 2. Repo layout and ownership

```
helpmate/
  README.md  .gitattributes (eol=lf)  .editorconfig  .env.example
  docs/ architecture.md · api-contract.md · adr/ · setup-windows.md · plan.md (this plan)
  contracts/openapi.yaml            # generated from FastAPI, committed; CI fails on drift   [ALL]
  backend/  (uv, Python 3.12)
    src/helpmate/
      main.py  container.py          # composition root: picks adapters from env              [C wk1, then ALL]
      settings.py                                                                              [C wk1]
      domain/ports.py  models.py     # Protocols + shared types — changes need all 3 reviewers [ALL]
      api/ routers + schemas/        # the contract: chat, proposals, tasks, folders, reminders,
                                     #   memory, voice, push, settings, auth, audit, health   [C wk1 stubs → owners]
      agent/  memory/  eval/                                                                   [A]
      adapters/ ollama_llm.py ollama_embed.py                                                  [A]
                postgres_*.py gmail.py gcal.py s3_files.py                                     [B]
                speech_http.py webpush_notifier.py quiet_hours.py                              [C]
                fakes/ (fake_llm, fake_agent, memory_repos, fake_stt, fake_tts, log_notifier) [C wk1]
      worker/  (job queue, scheduler, outbox)                                                  [B]
    tests/
  services/speech/  (own uv env)     # faster-whisper + kokoro-onnx; POST /transcribe, /speak  [C]
  web/  (Vite + React + TS PWA)                                                                 [C]
    src/api/ (generated schema.d.ts, client.ts, sse.ts)  src/mocks/ (MSW)  src/features/*  src/sw.ts
  infra/docker-compose.yml           # pgvector Postgres + SeaweedFS, bound to 127.0.0.1       [B, C bootstraps]
  scripts/ bench_models.py · dev.ps1 · export_openapi.py
  .github/ workflows/ci.yml · CODEOWNERS · pull_request_template.md
```

## 3. The plug-in seams (the core of the "just plugs in" design)

| Seam | Interface (in `domain/ports.py` or the contract) | Fake used until ready | Real impl (owner) | Switch |
|---|---|---|---|---|
| Agent | `AgentPort.run(session, text) -> AsyncIterator[ChatEvent]` | `ScriptedAgent` (regex → proposal) | agent loop + policy engine (A) | `HELPMATE_AGENT=scripted\|loop` |
| LLM | `LLMPort.chat(messages, tools, stream)`, `EmbeddingPort.embed()` | `FakeLLM` | Ollama adapter (A) | `HELPMATE_LLM=fake\|ollama` |
| Data | `TaskRepo`, `ReminderRepo`, `ProposalRepo`, `AuditRepo`, `PushSubRepo`… | in-memory repos | Postgres + Alembic (B) | `HELPMATE_REPO=memory\|postgres` |
| Scheduler | `Scheduler.enqueue(job)`, worker calls `NotifierPort` | asyncio `DevScheduler` (10 s tick) | Postgres job queue (B) | `HELPMATE_SCHEDULER=dev\|pg` |
| Notify | `NotifierPort.notify(user_id, Notification{id,title,body,url,tag,kind,urgent})` | `LogNotifier` | `WebPushNotifier` + `QuietHours` decorator (C) | `HELPMATE_NOTIFIER=log\|webpush` |
| Voice | `STTPort.transcribe(bytes, mime)`, `TTSPort.speak(text, voice)` | `FakeSTT`/`FakeTTS` | HTTP → speech service (C) | `HELPMATE_STT/TTS=fake\|http` |
| Auth | session cookie + TOTP | `dev` (auto-login single user) | password + TOTP (B/A) | `HELPMATE_AUTH=dev\|totp` |
| Frontend ↔ backend | `contracts/openapi.yaml` → generated TS types | **MSW** mocks in browser | real FastAPI | `VITE_API_MOCK=1\|0` |

- **`GET /api/health`** returns which adapter is active for each seam. The web app has a *System status* panel that shows fake vs real, so you can watch teammates' parts plug in (useful in the demo video too).
- **Port contract tests:** each port has one shared test suite (`tests/contracts/test_<port>.py`) that is run against both the fake and the real adapter. This stops a fake from behaving differently from what A/B ship. B's Postgres scheduler (`SKIP LOCKED`) is tested only against real Postgres in CI, because the fake can't reproduce it.
- **Contract change process:** schemas live in `backend/src/helpmate/api/schemas/`. `scripts/export_openapi.py` writes `contracts/openapi.yaml`, and `npm run gen:api` regenerates the TS types. CODEOWNERS requires all 3 reviewers on `contracts/**`, `domain/ports.py` and `api/schemas/**`. Additive changes only after week 2; breaking changes need a version bump.
- **SSE chat events** are a pydantic discriminated union `ChatEvent`, exposed in OpenAPI so the frontend gets typed events: `message.delta{text}`, `tool.started{call_id,tool,args}`, `tool.result{call_id,ok,summary}`, `proposal.created{Proposal}`, `message.done{message_id,ttft_ms,tokens}`, `error{code,message}`.
- **Proposal** = `{id, tool, title, summary, args, preview?, risk: write|external, status: pending|approved|rejected|executed|failed, created_at}`. Decision: `POST /api/proposals/{id}/decision {decision: approve|reject|edit, args?}`. Direct user edits in the UI need no approval; only *agent-initiated* writes do.

### API contract v0.1 (C writes the stubs in week 1; owners fill them in)
- auth: `POST /api/auth/login`, `POST /api/auth/mfa`, `POST /api/auth/mfa/enroll`, `POST /api/auth/logout`, `GET /api/me`
- chat: `POST /api/chat/sessions`, `GET /api/chat/sessions/{id}/messages`, `POST /api/chat/sessions/{id}/messages {text, source:text|voice}` → `text/event-stream`
- proposals: `GET /api/proposals?status=pending`, `POST /api/proposals/{id}/decision`
- organize: `GET/POST /api/folders`, `GET /api/folders/{id}/items`, `GET/PATCH /api/tasks?horizon=week|term|year|someday`, `GET /api/reminders`, `GET /api/today`
- memory: `GET /api/memory/suggestions`, `POST /api/memory/suggestions/{id}/decision`, `GET/DELETE /api/memory/facts`, `GET /api/export`
- voice (C): `POST /api/voice/transcribe` (raw audio body, `Content-Type: audio/webm|mp4|ogg|wav`; never multipart, so nothing spools to disk) → `{text, language, duration_ms, stt_ms}`; `POST /api/voice/speak {text, voice?}` → `audio/wav`
- push (C): `GET /api/push/vapid-public-key`, `POST/DELETE /api/push/subscriptions`, `POST /api/push/test`, `POST /api/push/ack {notification_id, received_at}`
- settings (C): `GET/PUT /api/settings/notifications {quiet_hours{start,end,tz}, max_per_hour, private_previews}`
- audit (B): `GET /api/audit` · health: `GET /api/health`

---

## 4. Step-by-step

### Phase 0 — Tools
**Any dev machine:** Git, Node 22 LTS, uv (`winget install astral-sh.uv` or `scoop install uv`), gh, and Docker Desktop. Make sure `git config user.email` matches your GitHub account.

**XPS (Windows 11):**
- NVIDIA driver **≥ 570** (required for Pascal / compute 6.1 on current Ollama), and `nvidia-smi` must work.
- Git (`git config --global core.longpaths true`), Node 22 LTS, uv, Docker Desktop (WSL2 backend), gh, VS Code, and Tailscale later (week 4).
- **Ollama from the official installer only.** It ships both CUDA 12 and CUDA 13 backends, and some third-party installers pick CUDA 13 on Pascal, which silently falls back to the CPU. Ollama runs natively on Windows, not in Docker.
- `%UserProfile%\.wslconfig` → `[wsl2]` `memory=3GB` (the default is 50% = 8 GB, which starves Ollama and whisper on 16 GB).

### Phase 1 — Repo and governance (week 1, C leads)
1. `git init -b main` with `core.longpaths true`.
2. `.gitattributes` (`* text=auto eol=lf`), `.editorconfig`, `.gitignore` (Python/Node/.env/models), MIT or course-appropriate LICENSE, and a README with a 5-command quickstart.
3. `gh repo create helpmate --private`, then invite teammates. Branch protection on `main`: PRs only, 1 review, CI green, squash merge. Branch names are `feat/<area>-<desc>`, commits follow Conventional Commits.
4. `CODEOWNERS` (A: `agent/ memory/ eval/`; B: `worker/ adapters/postgres* gmail* gcal* infra/`; C: `web/ services/speech/ adapters/speech* webpush*`; ALL: `contracts/ domain/ports.py api/schemas/`), plus a PR template and issue templates. GitHub Project board with columns per week.

### Phase 2 — Walking skeleton (week 1)
1. **Backend:** `uv init` with Python 3.12, FastAPI, uvicorn, pydantic-settings, `tzdata` (Windows `zoneinfo` has no timezone DB, so DST tests break without it), sse-starlette (or a hand-rolled StreamingResponse with a 15 s heartbeat comment and `Cache-Control: no-cache`), and dev tools pytest, ruff and httpx. Write `ports.py`, the fakes, `container.py`, stub routers for the whole v0.1 contract, and `/api/health`. `ScriptedAgent` handles "remind me to X at T" → a `create_reminder` proposal. On approve it stores the reminder in memory, and `DevScheduler` → `LogNotifier` fires it.
2. **Contract:** `scripts/export_openapi.py` → `contracts/openapi.yaml`.
3. **Web:** `npm create vite@latest web -- --template react-ts`, then React Router, TanStack Query, `openapi-typescript` + `openapi-fetch`, MSW v2 (`npx msw init ./public --save`), `vite-plugin-pwa` (injectManifest, `srcDir: src`, `filename: sw.ts`), Vitest + Testing Library + axe. Screens: Chat (streaming), Approvals inbox and cards, Today, System status (shows a **FAKE** banner for each fake seam). The Vite dev proxy sends `/api` → `127.0.0.1:8000` so everything is same-origin.
   - **Two service workers can't share scope `/`**, and MSW's worker and the push SW would replace each other. Mode `mock` runs MSW with PWA `devOptions` off. Push and PWA work is always tested with `VITE_API_MOCK=0` against the real backend running its fakes, so the backend's fakes are the mock for that path.
   - The chat stream is mocked with MSW `http.post` returning a `ReadableStream` as `text/event-stream`. MSW's `sse()` helper expects EventSource, and our client POSTs with fetch.
4. **Speech service stub:** FastAPI with `/transcribe` and `/speak` backed by fake engines (the real models come in Phase 5).
5. **Infra:** `docker-compose.yml` with `pgvector/pgvector:0.8.6-pg17` (pinned) and `chrislusf/seaweedfs` single node (`weed mini -dir=/data`, with S3 on 8333 and the bucket created from `S3_BUCKET` env; confirm the exact args against the wiki on first run). Ports bound to `127.0.0.1:` (Docker on Windows otherwise publishes on 0.0.0.0), named volumes, healthchecks. B takes it over.
6. **CI (`ci.yml`):** backend job (uv sync, ruff, pytest, OpenAPI drift check), web job (npm ci, eslint, tsc, `gen:api` drift check, vitest, build) and speech job (ruff, pytest with the fake engine). Integration tests against real Postgres come later from B.
7. `scripts/dev.ps1` starts compose, backend, speech and web in one go. **Checkpoint:** "remind me to call mom at 5pm" → card → approve → log line at 17:00, with all fakes and no GPU. Push to GitHub.

### Phase 3 — Ollama on the XPS and the model benchmark (week 1, feeds A)
1. Install Ollama (official installer), check `nvidia-smi`, then pull `llama3.2:3b` (2.0 GB), `qwen3:4b` (2.5 GB, use `think:false`) and `nomic-embed-text` (274 MB, 768-dim). Optionally add `llama3.1:8b` as a CPU-spill comparison. User env vars:
   - `OLLAMA_HOST=127.0.0.1:11434` (never expose it)
   - `OLLAMA_KEEP_ALIVE=30m` while developing, which avoids cold reloads; for the sustainability measurement, compare against the default 5m
   - `OLLAMA_CONTEXT_LENGTH=4096`
   - `OLLAMA_FLASH_ATTENTION=1`

   Keep the embedding model off the GPU or unloaded when chat needs the VRAM.
2. `ollama run llama3.2:3b`, then `ollama ps` should show *100% GPU*. That confirms the 1050 Ti is actually used.
3. `scripts/bench_models.py`: for each model, measure TTFT, tokens/s, VRAM (`nvidia-smi`) and tool-call validity on ~15 seed prompts from the golden set. Write a markdown table to `docs/benchmark-xps.md`, and re-run it on the demo host later.
4. Minimal `OllamaLLM` adapter so the skeleton runs with `HELPMATE_LLM=ollama`. A owns and extends it.

### Phase 4 — Web app core (weeks 2–3, while A builds the agent and B the data layer)
Everything here is built against MSW mocks, so it doesn't wait on A or B.
- **Chat:** fetch-based SSE client (POST body + `ReadableStream`), with AbortController for Stop and a TTFT display.
- **Approval cards:** Approve, Edit (a form generated from `args`) and Cancel. Email preview renders the full body. Keyboard- and screen-reader-accessible.
- **Organize views:** folders (PARA + custom folders with custom fields such as Books: title/author/status/rating), tasks by horizon, reminders, Today board, and the memory suggestion review queue (approve/reject, with source shown).
- **Auth screens:** login, TOTP enrol (QR) and verify.
- **PWA:** manifest, icons, installability, offline shell.
- **Accessibility:** WCAG 2.1 AA — axe in tests, visible focus, 4.5:1 contrast, `aria-live` for streamed replies.

### Phase 5 — Voice (week 4, C leads)
1. **Speech service (Python 3.12):**
   - `faster-whisper` 1.2.x on CPU with `compute_type="int8"`, `vad_filter=True`, `beam_size=1`, `cpu_threads=4–6`. PyAV bundles FFmpeg, so no system ffmpeg is needed. Model size is picked by measurement (see §6).
   - `kokoro-onnx` 0.6.x, chosen over torch `kokoro`: no torch, and espeak-ng comes bundled via `espeakng-loader`. `scripts/get_models.ps1` downloads `kokoro-v1.0.int8.onnx` (114 MB) and `voices-v1.0.bin` (28 MB) from the **model-files-v1.1** release into `services/speech/models/` (git-ignored).
   - Audio is handled in memory only, and logs record only durations.
2. **Core adapters:** `speech_http.py` implements STTPort/TTSPort. `/api/voice/*` routes proxy to the speech service.
3. **Web:** `PushToTalkButton` (hold, or tap-to-toggle for accessibility, plus Space-bar support) using MediaRecorder. The mime is picked by `isTypeSupported` and sent to the server: Chrome records webm/opus, and Safari 18.4+ records webm/opus too, with mp4 on older versions. Commit real Chrome and iPhone recordings as test fixtures. Upload → transcript shown for a quick edit → sent as `source: voice`. Replies are spoken sentence by sentence with `useSpeaker` (start TTS on the first finished sentence).
4. Measure end to end, **until the first audio plays**: upload + `stt_ms` + TTFT + first-sentence TTS against the ≤ 4 s target. Report requests with and without a tool call separately, since a tool call adds a second LLM round trip. The estimate on the XPS is ~2.8–3.5 s without a tool call.

### Phase 6 — Notifications (week 4, C leads)
1. Generate VAPID keys once (kept in `.env`, never committed, and the **same keys on every host**). `WebPushNotifier` uses `pywebpush` 2.5.x (`webpush_async`). **Set `ttl`** (e.g. 3600 s): the default `ttl=0` drops the push if the phone is unreachable at that moment. Reminders also send `Urgency: high`. Subscriptions that return 404/410 are pruned.
2. `QuietHoursNotifier` decorator: defers non-urgent notifications during quiet hours and enforces `max_per_hour`. `private_previews` sends generic text ("You have a reminder") so no personal content passes through the push service.
3. **Service worker (`sw.ts`):** `push` → `showNotification` + POST `/api/push/ack`, and `notificationclick` → focus or open the URL. **UI:** an "Enable notifications" button (the permission prompt must come from a user gesture), a test-push button and notification settings.
4. B's scheduler just calls `NotifierPort.notify()`. Nothing in the worker knows about Web Push.
5. **Latency metric:** `ack.received_at - reminder.due_at`. Target: 95% within 60 s.

### Phase 7 — Secure access from the phone (week 4, with B)
1. **Prod mode:** FastAPI serves `web/dist` at `/` and the API at `/api` (single origin, `SameSite=Strict` HttpOnly session cookie).
2. **Tailscale on the XPS and the phone:** `tailscale serve` (tailnet-only HTTPS on `*.ts.net`) for daily use. `tailscale funnel` (public) only when O7 is being demoed, and only once 2FA and rate limiting are live. TLS terminates on the laptop, as the architecture figure shows. Mic and service worker need HTTPS on the phone, and the `ts.net` cert provides it.
3. **iPhone:** add to Home Screen first (manifest `display: standalone`), or push won't work. The installed PWA has its **own cookie jar** separate from Safari, so the user logs in inside the PWA. Android Chrome works in the browser.
4. **The PWA install and push subscription are bound to the hostname.** Give the machine a stable Tailscale name (e.g. `helpmate`) so that moving the demo to the RTX 4070 laptop keeps the same `helpmate.<tailnet>.ts.net` origin. Otherwise every phone has to reinstall and re-subscribe. Decide the demo host by week 4.
5. **Spike test in week 1** (short one): SSE through `tailscale serve`/`funnel`, which isn't documented. The heartbeat keeps the stream alive, and if buffering shows up the fallback is chunked NDJSON over the same POST.

### Phase 8 — E2E, DST and demo (week 6, C leads) → midterm video
- Playwright E2E (chat → approve → reminder → push-ack, with axe checks) runs in CI with fakes.
- DST test (with A/B): simulated clock across **Nov 1, 2026** for recurring reminders.
- Demo script, a 3-minute video and a rehearsal.

---

## 5. Merged timeline (project week → course week, assuming course week 1 = Sep 7 so recess = Thanksgiving week)

| Proj wk (Mon) | Course wk | Work (lead) | C deliverable |
|---|---|---|---|
| 1 (Sep 28) | 4 · updated spec due | repo, CI, contract, skeleton, benchmark (**C**) | Phases 0–3 |
| 2 (Oct 5) | 5 | agent loop + approval cards, folders/tasks/reminders, 2FA (A) | chat + approvals + auth UI |
| 3 (Oct 12) | 6 · recess | memory v1, reminder scheduling (A) | organize views, memory queue, PWA shell |
| 4 (Oct 19) | 7 | voice, phone push, custom folders, secure deploy (**C**) | Phases 5–7 |
| 5 (Oct 26) | **8 · midterm: design doc + 3-min video** | brief/check-in/weekly plan, Gmail + **Google Calendar** draft/approve (B); feature freeze | brief/plan views, email/event preview cards, **video** |
| 6 (Nov 2) | 9 | E2E + DST tests, demo (**C**) | Phase 8 |
| 7 (Nov 9) | 10 | inbox triage + prompt-injection defences, calendar import (B) | triage UI |
| 8 (Nov 16) | 11 | document Q&A with citations, file vault (A) | upload + citations UI |
| 9 (Nov 23) | 12 | backups, eval in CI, security review, **network-monitoring privacy test** (B) | SUS survey (≥ 5 peers), perf numbers |
| 10 (Nov 30) | 13 | final report, video, presentation | final demo |

The midterm submission (course wk 8) comes **before** the spec's week-6 demo, so the skeleton, chat, approvals, voice and push must be video-ready by ~Oct 26. Confirm the course week numbers on Avenue.

## 6. Hardware reality (XPS, 4 GB VRAM, 16 GB RAM)
- **LLM:** 3–4B models at Q4 (llama3.2:3b is Llama-family, per the Updated spec; qwen3:4b / qwen2.5:3b are candidates for better tool calling). 7–8B won't fit in 4 GB and would partly run on CPU; benchmark it only for comparison. The spec's "4–9B, VRAM ≤ 7.5 GB" becomes "3–4B, VRAM ≤ 3.8 GB" on the XPS.
- **VRAM:** llama3.2:3b is ~2.0 GB weights + ~0.45 GB KV at 4K + ~0.4 GB CUDA overhead ≈ **3 GB**. qwen3:4b is ≈ 3.5 GB (tight).
- **STT/TTS on CPU:** whisper `base` int8 (~0.5 GB, ~0.6 s for a short clip). `base.en`/`small.en` are faster or more accurate but English-only, and the spec promises multilingual STT, so the default is multilingual `base` with the language configurable. Whisper pads audio to a 30 s window, so `small` costs ~1–2 s per clip on the 8750H. Kokoro int8 ~0.5 GB. Stream TTS by sentence.
- **RAM budget (~11–12 GB total):** Windows + IDE + browser ~5–6 GB · WSL2/Docker 3 GB (capped) · Ollama host side ~1 GB · backend + worker ~0.5 GB · whisper + Kokoro ~1 GB · Vite ~0.5 GB.

## 7. Verification
- **Skeleton (all fakes, no GPU):** `scripts/dev.ps1` → browser → "remind me to call mom in 1 minute" → proposal card → Approve → the `LogNotifier` line appears about 60 s later. `/api/health` shows every adapter as `fake`.
- **CI green on the first PR:** ruff, pytest, vitest, tsc, build, plus the OpenAPI and TS-types drift checks (change a schema without regenerating and confirm CI fails).
- **XPS + Ollama:** `HELPMATE_LLM=ollama`, and `ollama ps` shows 100% GPU. Same flow with the real model. Benchmark table committed.
- **Voice:** say "remind me to buy milk at 6pm" → transcript → card → the reply is spoken. The logged `stt_ms`/TTFT/TTS numbers are within target. Confirm no audio files exist on disk afterwards.
- **Push:** phone over the Tailscale URL → install PWA → Enable notifications → Test push arrives → a reminder due in 2 min arrives within 60 s and the ack is recorded. Quiet hours hold back a non-urgent push.
- **Plug-in proof:** flip one env var at a time (`HELPMATE_REPO=postgres`, `HELPMATE_AGENT=loop`, …) as teammates deliver. With zero web or voice code changes, the E2E suite still passes.

## 8. Risks
- **Contract drift between members:** handled by the CODEOWNERS gate, CI drift checks and additive-only changes after week 2.
- **4 GB VRAM and tool-calling quality of 3B models:** the benchmark decides. The ScriptedAgent fallback keeps the demo safe.
- **Windows pitfalls:** CRLF (`.gitattributes`), long paths, Docker publishing on 0.0.0.0 by default (always bind `127.0.0.1:`), WSL2 memory.
- **iOS push quirks:** Home Screen install is required, the PWA has a separate cookie jar, and install and subscription are tied to the hostname. Test on Android and iOS early (week 4, not week 6).
- **Model licences:** qwen2.5:3b uses the Qwen licence, not Apache. Note it in the report if it wins the benchmark. The Updated spec asks for a Llama-family model, so llama3.2:3b is the default unless the benchmark clearly says otherwise.