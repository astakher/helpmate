# HelpMate — notes for Claude Code

Local-first agentic personal assistant (ENG TECH 4FD3, Fall 2026). Full plan: `docs/plan.md`.
Machine setup: `docs/setup-windows.md`. Contract rules: `docs/api-contract.md`.

Team workstreams: **A** agent/LLM/memory/eval · **B** backend data/integrations/security/deploy ·
**C** (Aman, repo owner) web app, voice, notifications. C also leads project weeks 1, 4 and 6.

## Testbed vs. deliverable (read before changing anything)
- This repo is Aman's **testbed**: the whole app lives here so Part C can be tested end to end.
  Everything for A or B here (agent, LLM, memory, eval, data, scheduler, auth, integrations) is a
  **stand-in**. The group's shared repo keeps A's and B's real code; only **Part C** is copied across,
  and it must plug in unchanged.
- **Part C** = `web/`, `services/speech/`, and backend `adapters/speech_http.py`,
  `adapters/webpush_notifier.py`, `adapters/quiet_hours.py`, `api/routes/{voice,push,settings}.py`
  with their tests. It may import only `helpmate.domain`, `helpmate.api.deps`, `helpmate.api.schemas`,
  `helpmate.settings` (and itself); never `agent/ memory/ eval/ worker/`, A/B adapters, or fakes
  (fakes are fine in tests). `tests/test_part_c_boundary.py` enforces it.
- New A/B stand-in files start with `# Stand-in for Workstream A/B - not part of the Part C deliverable`.
- Contract changes stay additive and are logged in `docs/part-c.md` §7.
- Full handoff guide: **`docs/part-c.md`**. Leave `.github/CODEOWNERS` as is (template for the shared repo).

## Layout
- `backend/` — FastAPI core plane (uv, Python 3.12). `src/helpmate/domain/ports.py` = the seams;
  `container.py` picks adapters from `HELPMATE_*` env; `agent/policy.py` = approval invariant;
  `adapters/fakes/` = a fake for every port; `eval/bench.py` = model benchmark (`helpmate-bench`).
- `services/speech/` — separate speech service on :8001 (own uv env). Fake engine, or real
  faster-whisper + kokoro-onnx with `SPEECH_ENGINE=real` (Phase 5).
- `web/` — React 19 + TS + Vite PWA. `src/api/schema.d.ts` is GENERATED; `src/mocks/` = MSW
  handlers used by `npm run dev:mock` and by all unit tests; `src/sw.ts` = service worker (push + ack).
- `contracts/openapi.yaml` — GENERATED from backend schemas; CI fails on drift.
- `infra/docker-compose.yml` — pgvector Postgres + SeaweedFS, ports bound to 127.0.0.1.
- `data/` — git-ignored secrets: the Google OAuth client + token, and the 2FA secret (`auth.json`)
  once `HELPMATE_AUTH=totp` is on. Never print or commit its files.

## Commands
```powershell
./scripts/dev.ps1                      # API :8000 + speech :8001 + web :5173 (fakes unless .env says otherwise)
./scripts/dev.ps1 -Mock                # web only, MSW mocks
cd backend; uv run pytest -q; uv run ruff check src tests ../scripts; uv run ruff format src tests ../scripts
cd backend; uv run python ../scripts/export_openapi.py     # after ANY schema/route change
cd web; npm run gen:api; npm test; npm run lint; npm run typecheck; npm run build
cd backend; uv run helpmate-bench --models llama3.2:3b qwen3:4b   # needs Ollama; writes docs/benchmarks/
```

## Rules that keep the plug-in design working
- Routers and the agent depend on **ports only**. New real adapter = implement the Protocol, replace the
  `_not_yet(...)` branch in `container.py`, flip the env var. Add it to the matching
  `tests/contracts/` factory so it passes the same suite as the fake.
- **No agent-initiated write runs without approval.** Write tools go through `PolicyEngine`; every new
  write tool needs a `SAMPLE_ARGS` entry in `tests/test_policy.py` (the test enforces it).
- Contract changes: edit pydantic schemas → export OpenAPI → `npm run gen:api` → commit both.
  Additive only after week 2. `contracts/`, `domain/`, `api/schemas/` need all three reviewers.
- Voice upload is a **raw request body** (never multipart) so audio never spools to disk.
- All datetimes are timezone-aware UTC in storage; owner timezone at the edges. Keep `tzdata`.

## Gotchas already hit (don't re-learn them)
- TypeScript is pinned to **5.9.x**: openapi-typescript 7 and typescript-eslint don't support TS 6/7 yet.
- openapi-fetch must get a lazy `fetch` (see `web/src/api/client.ts`), or MSW can't intercept in tests.
- Forms that swap in place need distinct React `key`s (login bug: code field inherited the username).
- MSW's worker and the PWA service worker can't share scope `/`: PWA SW is prod-only, MSW dev-only.
- `astral-sh/setup-uv` has no floating major tag — pin exact (`v10.2.0`).
- Starlette `StaticFiles` normalises paths with OS separators; check `scope["path"]`, not `path`.
- Windows: `.gitattributes` forces LF (ps1 = CRLF); Docker ports must be `127.0.0.1:`-bound.
- Never return a value from a `useEffect` arrow (`() => el.scrollIntoView()`): Chrome's scroll
  methods now return a Promise, React calls it as cleanup → blank page. jsdom doesn't catch it.
- Ollama 0.34 keeps 1 GiB VRAM free by default and spills layers to CPU on 4 GB cards even when
  the model fits. `LLAMA_ARG_FIT_TARGET=512` (MiB) fixes it; check `ollama ps` = 100% GPU.
- `qwen3:4b` is the thinking-only 2507 build: `think:false` is ignored. Use `qwen3:4b-instruct`
  for a non-thinking comparison.
- Speech: pin `av<19` (faster-whisper 1.2.1 passes `metadata_errors`, which PyAV 19 removed); use
  Kokoro **fp32** (int8 is ~10x slower without AVX-512 VNNI); `uv sync` without `--extra real` removes
  the real engine (`uv run` doesn't). Recordings under ~0.4 s are bare webm headers → 422, not 500.
- Web Push TLS uses certifi, not the Windows store: Windows fetches roots lazily, and Python lacked
  Apple's (COMODO ECC), so iPhone pushes failed while Chrome's (FCM) worked.
- faster-whisper must load with `local_files_only=True`: otherwise it asks huggingface.co for a newer
  model at every start and keeps the connection open (caught by `scripts/privacy_check.py`).
- Google OAuth apps in "Testing" get 7-day refresh tokens; the adapters turn that into
  `GoogleNotConnected` ("re-run google_auth.py"), which read tools report and card checks show.
  Reverse DNS can't tell FCM push from Gmail/Calendar (both `*.1e100.net`), so the privacy check
  allows that row only for the API process.
- Small models invent email addresses ("mom@example.com"): `send_email` keeps only addresses the
  owner typed (`resolve(..., said=text)`), otherwise the agent asks.
- llama3.2:3b routes "show me …" to the first list route it sees, and writes the *string* "null"
  into fields it doesn't need (Gmail then searched `from:null null`). Fixes: topic words decide which
  routes the router is offered (`routes_for`), and `resolve()` drops placeholder values. A benchmark
  `~` (contains) check can pass garbage; add a `!~` check for it.
- State inside a page component dies when you navigate away (the chat used to reset after a trip
  to Memory). The conversation lives in `ChatProvider` above `<Routes>`; its session id is in
  localStorage and reloads restore it from `GET /api/chat/sessions/{id}/messages` + its proposals.
  The Chat page's sidebar (`ChatList`) lists, opens and deletes chats; history loads are versioned
  (`loadToken`) so a slow load can't overwrite the chat opened after it.
- After a web rebuild, an open tab keeps running the old bundle until it fully reloads (the PWA
  caches it): "still broken" reports after a fix → Ctrl+Shift+R first. Check against a fresh
  profile with real Chrome: `uv run --no-project --with playwright python <script>` using
  `p.chromium.launch(channel="chrome")` (no browser download needed).
- Memory-search thresholds are model-specific: 0.55 / margin 0.08 are for nomic-embed-text (re-run
  `helpmate-memory-bench` if the model changes); bag-of-words `FakeEmbeddings` need ~0.3 in tests.
- `uv sync` (and `uv run` after a pyproject change) fails while the API runs (`helpmate-api.exe` is
  locked): stop the API first, or use `uv run --no-sync`.
- The benchmark must not send `keep_alive`: its "10m" overrode OLLAMA_KEEP_ALIVE=30m, so the app's
  next message after a run paid a ~5 s model reload.

## Status (update as phases land)
- Done: Phase 0–2 (repo, CI, contract v0.1, walking skeleton), benchmark script, Phase 4 web
  (tasks, folders + custom fields, memory review, login/TOTP screens, settings, edit-then-approve).
- Done: **Phase 3 on the XPS (Sep 29)**. Driver 582.66, Ollama 0.34.4 (official), llama3.2:3b
  **100% GPU, 2.55 GB VRAM** (needs `LLAMA_ARG_FIT_TARGET=512`). Skeleton checked in Chrome with
  fakes and with `HELPMATE_LLM=ollama` (warm TTFT ≈ 0.5 s). Not yet run on a real phone.
- Benchmark (`docs/benchmarks/desktop-o05c1es.md`, 15 seed prompts): llama3.2:3b — tool choice
  80%, args valid 91%, args correct 64%, TTFT median 0.9 s, 25 tok/s, 100% GPU. qwen3:4b — 100%
  on all three, but the tag is the thinking-only 2507 build (ignores `think:false`, ~48 s per
  answer) and spills 16% to CPU.
- **Default model: llama3.2:3b** — the only one meeting the speed and 100%-GPU targets, and the
  Updated spec asks for Llama-family. Misses to fix in A's agent: relative times ("in 10 minutes"
  → `PT10M`), empty `recurrence`, and tool calls on small talk. See the report's Misses list.
- **Tool-calling fixes prototyped for A** (stand-in, `agent/llm_tools.py` + `agent/when.py`,
  `docs/benchmarks/llama-tool-calling-fixes.md`): time words resolved in code + a no-tools routing
  call → llama3.2:3b **tool choice 100% / 94%, args 100%** on seed / held-out (31 prompts), plain
  reply first word 0.46 s, tool call ~1.5–1.9 s. A prompt rule alone did nothing for small talk.
- **`HELPMATE_AGENT=loop` works** (stand-in for A, `agent/loop.py`): routing → one tool →
  `resolve()` + retry once → `PolicyEngine` (cards as before); plain replies use `reply_prompt()`
  with recent history. Live on the XPS: small talk ≈ 1 s, list ≈ 1.2 s, a reminder card ≈ 2–3 s
  (mostly ~40 tokens of tool-call JSON at 24 tok/s). `scripted` stays the default in `.env.example`.
- **Phase 6 Web Push works on desktop Chrome** (Sep 30): `HELPMATE_NOTIFIER=webpush` =
  `QuietHoursNotifier(WebPushNotifier)`; Settings → Enable / Send test (shows latency). Measured:
  test push and a model-created reminder both **~1 s from due to shown** (target ≤ 60 s). Needs
  `./scripts/dev.ps1 -Prod` (:8000). Phone push needs Phase 7 (HTTPS via Tailscale).
- **Phase 5 voice works in Chrome** (Sep 30): push-to-talk (hold, tap, or Space/Enter) → transcript
  to edit (or "send right away") → reply spoken chunk by chunk, with a timing line against the ≤ 4 s
  target. `SPEECH_ENGINE=real`: whisper `base` int8 1.2 s (0.66 s with `language=en`) for 2.4 s of
  speech, Kokoro fp32 0.6 s for the first chunk. Estimated ~3 s for plain questions, ~4–4.5 s with a
  tool call (the model's tool call is 2–3 s).
- **Phase 7 Tailscale works** (Sep 30): `https://helpmate.<tailnet>.ts.net` via `tailscale serve`
  (tailnet only; funnel off), SSE streams through it. iPhone 15 Pro: PWA from the Home Screen, test
  push shown 1.0 s after sending (needed certifi TLS for web.push.apple.com, see gotchas).
- **Privacy check PASS** (Sep 30, `scripts/privacy_check.py` → `docs/privacy/<host>.md`): during chat,
  a proposal, a voice round trip and a test push, HelpMate's processes reached only loopback (after
  fixing Whisper's Hugging Face check), Tailscale devices and push services.
- **Postgres works** (Sep 30; stand-in for B, `adapters/postgres_repos.py` + Alembic `migrations/`):
  pgvector/pgvector:0.8.6-pg17 in Docker on 127.0.0.1, JSONB rows + typed columns, same contract suite
  as the fakes (16/16 with `HELPMATE_TEST_DATABASE_URL`), data survives API restarts.
- **Gmail + Google Calendar work** (Sep 30; stand-ins for B `adapters/gmail.py`, `gcal.py`,
  `google_oauth.py` and for A's tools): `HELPMATE_MAIL=gmail`, `HELPMATE_CALENDAR=google`, connected
  with `scripts/google_auth.py` (scopes `gmail.readonly`, `gmail.send`, `calendar.events`). Tools:
  `search_email`, `list_events`, `find_free_time` (read-only), plus `send_email` and `create_event`
  (risk external, approval card; the email card shows the whole message, the event card shows
  overlaps as `Proposal.warnings`), and `list_tasks`. Router has 10 routes with topic-word guards
  (`llm_tools.routes_for`): seed 100% / held-out 100% / connectors 91% (23), args 100%. Live on the
  owner's account: ~2 s per read. Fakes (`adapters/fakes/connectors.py`) otherwise.
- **Chat list + daily brief** (Oct 1): the Chat page has a sidebar (all chats, New chat, open,
  delete); the Today page is a daily brief (today's events with "Now", free time left, newest
  unread mail linking to Gmail, reminders, this week's tasks). `GET /api/today` reads Calendar and
  Gmail in parallel with an 8 s limit each; a failing one shows its own error. Live: ~1.2 s.
- **Memory is used in answers** (Oct 1; stand-in for A, `memory/retrieval.py`): approved facts are
  embedded locally (nomic-embed-text on the CPU, llama stays 100% GPU) and the ≤ 3 that match a
  message (score ≥ 0.55 and within 0.08 of the best) go into the reply/tool prompt; the chat shows
  "From memory: …"; a saved email address counts as given. "What do you remember about me?" →
  `list_memory`. recall@5 = 1.00 on 20 seeded facts (`helpmate-memory-bench`). Router: 11 routes,
  seed 100% / held-out 100% / connectors 92% (26), args 100%. Live: answers in ~1.0–1.3 s.
- Next: real login on (owner sets the password), Phase 8 Playwright E2E, weekly plan / check-in,
  midterm design doc + 3-min video ≈ Oct 26.
- `main` is protected (PR + review + 3 CI checks); owner can bypass while teammates aren't added yet.

## Backlog (Part C first; the full gap list with fixes is `docs/plan.md` §9)
- ~~[C] Edit button on the Memory page. It needs [A] PATCH /api/memory/facts/{id}. Build that
  endpoint here as a stand-in and record it as a contract change.~~ Done Sep 30 (`docs/part-c.md` §7).
- ~~[C] Phase 5 real voice~~ Done Sep 30. Left: start TTS on the first sentence while the reply is still
  streaming; a per-device "voice language" choice (auto vs en); record real Chrome + iPhone clips as fixtures.
- ~~[C] Phase 6 Web Push~~ Done Sep 30 on desktop. Left: test on a phone (after Phase 7); durable
  holds for quiet hours belong in B's job queue (today they're in memory).
- ~~[C] Phase 7 Tailscale~~ Done Sep 30 with `serve` + iPhone; the owner tested the app on the
  iPhone again Oct 1 (works). Left: test on Android; `funnel` only once B's 2FA and rate limiting
  exist.
- ~~[C] Add a React error boundary so a render error shows a message, not a blank page.~~ Done Sep 30
  (`web/src/ErrorBoundary.tsx`: around the pages, reset on navigation, and around the whole app).
- [C] Energy per request: `nvidia-smi` power is N/A on the 1050 Ti Max-Q; plan a wall-meter/HWiNFO or
  demo-host measurement.
- [C] Phase 8: Playwright E2E (chat → approve → reminder → push ack) + DST test across Nov 1.
- [A] Replace the stand-in `LoopAgent` with A's real loop (it can reuse `llm_tools` + `when.py`);
  skip the model when `intent_parser` already matches (cards 2–3 s → instant); grow the golden set
  to ≥ 60; try `qwen3:4b-instruct`.
  (Done as stand-ins: benchmark `rem-at` fix, thinking-model TTFT, held-out set, `--pipeline`.)
- [A] (stand-in) "permitted" permission tier (empty by default); golden set ≥ 60 (now 52 over three
  sets), 10 prompt-injection cases (email bodies are the obvious source); count extra or failed tool
  calls in the benchmark. (Done: calendar conflict + free-time tools; memory search + recall@5.)
- [A/B] Memory search keeps its vectors in process (re-embedded after a restart, ~35 ms per fact);
  B can move them to a pgvector column without changing `MemoryRetriever`'s interface.
- [B] Postgres: stand-in done (all repos, Alembic 0001, contract suite green). B owns the schema from
  here (FKs, retention, backups + restore drill); the durable job queue (`scheduler=pg`, SKIP LOCKED)
  is still unbuilt.
- [B] Gmail/Calendar: stand-in done (Sep 30). B moves the Google token from `data/google_token.json`
  to Postgres (encrypted), publishes the OAuth app (Testing mode = 7-day sign-ins), and adds reply
  threading (`EmailDraft.in_reply_to`) and ICS import.
- [B] Real login: stand-in `HELPMATE_AUTH=totp` works (Sep 30; `adapters/totp_auth.py`, password via
  `scripts/set_password.py`). **On for the owner's XPS since Oct 1** (username in
  `HELPMATE_OWNER_USERNAME`; every endpoint but `/api/health` answers 401 without a session; the
  cookie is Secure over Tailscale because `tailscale serve` sends `X-Forwarded-Proto: https` from
  127.0.0.1, which uvicorn trusts). Sessions live in the API's memory, so a restart signs every
  device out. Live checks against the running app now need the owner to sign in: use the fakes
  or ask, never weaken auth for testing. B moves users/secrets/sessions to Postgres and adds
  recovery codes. `tailscale funnel` stays off until rate limiting exists. See plan §9 item 11.
- [B] Recurring reminders: stand-in in `worker/recurrence.py` + `DevScheduler` (Sep 30, DST-tested);
  B's Postgres job queue must reuse `next_occurrence` or pass `tests/test_recurrence.py`.
