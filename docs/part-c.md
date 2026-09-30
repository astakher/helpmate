# Part C — handoff guide (web app, voice, notifications)

**Owner:** Aman Takher (Workstream C). **Readers:** Workstreams A and B, before Part C is copied into
the group's shared repo.

This repo (`astakher/helpmate`) is Aman's **testbed**. It contains the whole app so Part C can be
tested end to end, but everything in it that belongs to A or B (agent, LLM, memory, eval, data,
scheduler, auth, integrations) is a **stand-in**. The shared repo keeps A's and B's real code.
Only Part C moves across, and it has to plug in **without changes**.

## 1. Rules

1. **Part C is** `web/`, `services/speech/`, and these backend files with their tests:
   `adapters/speech_http.py`, `adapters/webpush_notifier.py`, `adapters/quiet_hours.py`,
   `api/routes/voice.py`, `api/routes/push.py`, `api/routes/settings.py`.
2. **Part C depends only on the shared contract.**
   - The web app talks to the backend **over HTTP only**, using `contracts/openapi.yaml`.
   - Part C's backend files import only `helpmate.domain` (ports, models, events), `helpmate.api.deps`,
     `helpmate.api.schemas`, `helpmate.settings`, and each other.
   - Part C never imports `agent/`, `memory/`, `eval/`, `worker/`, A/B adapters (`ollama_*`,
     `postgres_*`, `gmail*`, `gcal*`, `s3_*`), or fakes. Tests may use fakes.
   - `backend/tests/test_part_c_boundary.py` enforces this in CI (§6).
3. Anything built here for A or B stays in their area and is marked
   `Stand-in for Workstream A/B - not part of the Part C deliverable`.
4. Contract changes are **additive only**, and every one is recorded in §7.

## 2. Files that make up Part C

| Path | What it is | Status |
|---|---|---|
| `web/` | React 19 + TS + Vite PWA: chat, approvals, today, tasks, folders, memory, settings, login/2FA, system status, service worker (`src/sw.ts`) | built (Phase 4) |
| `services/speech/` | Speech service on `127.0.0.1:8001`: `POST /transcribe`, `POST /speak`, `GET /health`. Own uv env. | fake engine; real faster-whisper + Kokoro in Phase 5 |
| `backend/src/helpmate/adapters/speech_http.py` | `HttpSTT`, `HttpTTS`: call the speech service over loopback | built |
| `backend/src/helpmate/adapters/webpush_notifier.py` | `WebPushNotifier` (pywebpush, VAPID, TTL, 404/410 pruning) | Phase 6 |
| `backend/src/helpmate/adapters/quiet_hours.py` | `QuietHoursNotifier` decorator (quiet hours, `max_per_hour`, private previews) | Phase 6 |
| `backend/src/helpmate/api/routes/voice.py` | `/api/voice/*` | built |
| `backend/src/helpmate/api/routes/push.py` | `/api/push/*` | built |
| `backend/src/helpmate/api/routes/settings.py` | `/api/settings/notifications` | built |
| `backend/tests/test_voice_and_push.py` | route tests (voice, push, settings) | built |
| `backend/tests/test_speech_http.py` | `HttpSTT` / `HttpTTS` against mocked HTTP | built |
| `backend/tests/contracts/test_notifier.py` | shared `NotifierPort` suite; C adds the `WebPushNotifier` factory in Phase 6 | built (fake only) |
| `backend/tests/test_part_c_boundary.py` | import-boundary check (rule 2) | built |

## 3. What Part C provides

**Ports it implements** (`backend/src/helpmate/domain/ports.py`):

| Port | Real adapter (C) | Switch | Fake used until then |
|---|---|---|---|
| `STTPort.transcribe(audio, mime, language)` | `HttpSTT` → speech service | `HELPMATE_STT=http` | `FakeSTT` |
| `TTSPort.speak(text, voice)` → WAV bytes | `HttpTTS` → speech service | `HELPMATE_TTS=http` | `FakeTTS` |
| `NotifierPort.notify(Notification)` → `DeliveryResult` | `QuietHoursNotifier(WebPushNotifier)` | `HELPMATE_NOTIFIER=webpush` | `LogNotifier` |

**Endpoints it owns** (all under `/api`, all need a logged-in session via `current_user`):

| Endpoint | Purpose |
|---|---|
| `POST /voice/transcribe` | raw audio body (`audio/webm`, `mp4`, `ogg`, `wav`, `mpeg`; ≤ 5 MB; **never multipart**) → `Transcript` |
| `POST /voice/speak` `{text, voice?}` | → `audio/wav` |
| `GET /push/vapid-public-key` | → `{public_key}` for `PushManager.subscribe` |
| `POST /push/subscriptions`, `DELETE /push/subscriptions` | store/remove a browser's push subscription |
| `POST /push/test` | send a test notification |
| `POST /push/ack` `{notification_id, received_at}` | called by the service worker; this is how the 60-second delivery target is measured |
| `GET /push/deliveries` | delivery log with latency |
| `GET/PUT /settings/notifications` | quiet hours, `max_per_hour`, private previews, timezone |

**The web app** covers every screen in plan §4 Phase 4, plus the System status page that shows which
seams are still fake (from `GET /api/health`).

## 4. What Part C needs from A and B

**From the shared backend (both).** Part C's backend files use only these:

- `helpmate.domain.models`: `Transcript`, `Notification`, `NotificationKind`, `Delivery`, `DeliveryResult`,
  `PushSubscription`, `NotificationSettings`, `new_id`
- `helpmate.domain.ports`: `STTPort`, `TTSPort`, `NotifierPort`, `Clock`, and the repos below
- `helpmate.api.schemas.bodies`: `SpeakIn`, `AckIn`, `SubscriptionIn`, `UnsubscribeIn`, `VapidKeyOut`
- `helpmate.api.deps`: `ContainerDep`, `current_user`. The container must expose `stt`, `tts`,
  `notifier`, `clock`, `settings` and `repos`.
- `helpmate.settings.Settings` fields: `stt`, `tts`, `notifier`, `speech_url`, `vapid_public_key`,
  `vapid_private_key`, `vapid_subject`, `push_ttl_seconds`, `timezone`

**From B (data, scheduler, auth):**

- Postgres implementations of `PushSubscriptionRepo` (`upsert`, `remove`, `find`), `DeliveryRepo`
  (`record`, `ack`, `find`) and `SettingsRepo` (`get/put_notification_settings`). They must pass
  `tests/contracts/test_repositories.py`. That suite covers push subscriptions and deliveries today.
  `SettingsRepo` has no case yet, so B should add one: defaults returned before any `put`, then a round trip.
- The scheduler calls `NotifierPort.notify()` when a reminder is due, and records a `Delivery`
  (`due_at`, `sent_at`) so `/push/ack` can compute latency. The worker never knows about Web Push.
- `AuthPort` behind `current_user`: session cookie `helpmate_session`, `SameSite=Strict`, HttpOnly.

**Endpoints the web app calls** (it depends on the contract only, never on backend code):

| Owner | Endpoints |
|---|---|
| A (agent, tools, memory) | `POST /chat/sessions`, `POST /chat/sessions/{id}/messages` (SSE `ChatEvent` stream), `GET /proposals`, `GET /proposals/{id}`, `POST /proposals/{id}/decision`, `GET /tools`, `GET /memory/suggestions`, `POST /memory/suggestions/{id}/decision`, `GET /memory/facts`, `DELETE /memory/facts/{id}` |
| B (data, auth) | `GET/POST /folders`, `GET/POST /folders/{id}/items`, `GET/POST /tasks`, `PATCH /tasks/{id}`, `GET /reminders`, `POST /reminders/{id}/cancel`, `GET /today`, `GET /export`, `POST /auth/login`, `POST /auth/mfa`, `POST /auth/mfa/enroll`, `POST /auth/logout`, `GET /me` |
| shared | `GET /health` (adapter name + `fake` flag per seam) |
| C | the voice, push and settings endpoints in §3 |

## 5. Plugging Part C into the shared repo

1. **Copy** `web/`, `services/speech/`, the six backend files and the four test files from §2 to the
   **same paths** in the shared repo. Don't edit them. If something doesn't fit, it's a contract
   mismatch (step 2), not a Part C change.
2. **Check the contract matches.** The shared repo's `domain/`, `api/schemas/bodies.py`, `api/deps.py`
   and `settings.py` must provide everything in §4. Missing pieces come in as **additive** contract
   changes through the normal three-reviewer process, and get recorded in §7.
3. **Register the routers.** In `backend/src/helpmate/api/__init__.py`, include `voice`, `push` and
   `settings` in `api_router` (the prefix `/api` comes from there).
4. **Wire the container.** In `container.py`:
   - speech: if `settings.stt`/`settings.tts == "http"`, build one `httpx.AsyncClient(base_url=settings.speech_url)`
     and pass it to `HttpSTT` / `HttpTTS`; otherwise use the fakes
   - notifier: if `settings.notifier == "webpush"`, wrap `WebPushNotifier` in the `QuietHoursNotifier`
     decorator (planned shape: `QuietHoursNotifier(WebPushNotifier(settings, repos.push_subscriptions),
     repos.settings, clock)`; the exact signature is set in Phase 6); otherwise `LogNotifier`
   - close the HTTP clients on shutdown
5. **Regenerate the contract:** `cd backend; uv run python ../scripts/export_openapi.py`, then
   `cd web; npm run gen:api`. Both files must match what's committed (CI checks for drift).
6. **CI:** keep three jobs, as in this repo's `.github/workflows/ci.yml`: backend (ruff, pytest, OpenAPI
   drift; this includes the boundary test), speech (ruff, pytest) and web (npm ci, types drift, lint,
   typecheck, test, build). Node 22, Python 3.12, `astral-sh/setup-uv@v10.2.0`.
7. **Config:** copy the C rows from `.env.example` (`HELPMATE_STT/TTS/NOTIFIER`, `HELPMATE_SPEECH_URL`,
   `SPEECH_*`, `HELPMATE_VAPID_*`, `HELPMATE_PUSH_TTL_SECONDS`). Generate VAPID keys **once** and use the
   same keys on every host, or phones must re-subscribe.
8. **Verify:** run §6, then `./scripts/dev.ps1` and check that the System status page shows
   `stt/tts/notifier` flipping from FAKE when you change the switches.

## 6. Running Part C's tests on their own (fakes only)

No GPU, Ollama, Postgres or network needed.

```powershell
# backend: Part C routes and adapters, the NotifierPort contract suite, and the boundary check
cd backend
uv run pytest -q tests/test_voice_and_push.py tests/test_speech_http.py tests/contracts/test_notifier.py tests/test_part_c_boundary.py

# speech service (fake engine)
cd services/speech
uv run pytest -q

# web app (MSW mocks in place of the backend)
cd web
npm ci; npm test; npm run lint; npm run typecheck

# click through the UI against mocks, no backend at all
./scripts/dev.ps1 -Mock
```

The backend tests use `tests/conftest.py`'s fixtures `settings` (all fakes, `.env` ignored), `clock`
(`FakeClock`, Mon Oct 5 2026 12:00 Toronto), `app`, `container` and `client` (ASGI, no server). The
shared repo's `conftest.py` must provide the same fixture names.

## 7. Contract changes since v0.1

v0.1 = `contracts/openapi.yaml` as committed in `8d5f957`. Every change since must be additive.

| Date | Change | Kind | Why | Owner |
|---|---|---|---|---|
| Sep 2026 (Phase 4, `4d88ea0`) | `GET /api/tools` → `list[ToolInfo]` `{name, description, read_only, risk, parameters}` | additive endpoint + schema | the Edit-then-approve form is built from each tool's JSON Schema | A (stand-in here) |

Planned (not built yet): `PATCH /api/memory/facts/{id}` `{text}` → `MemoryFact`, plus
`MemoryRepo.update_fact`, for the Memory page's Edit button (see the backlog in `CLAUDE.md`).
