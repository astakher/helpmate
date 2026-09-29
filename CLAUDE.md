# HelpMate — notes for Claude Code

Local-first agentic personal assistant (ENG TECH 4FD3, Fall 2026). Full plan: `docs/plan.md`.
Machine setup: `docs/setup-windows.md`. Contract rules: `docs/api-contract.md`.

Team workstreams: **A** agent/LLM/memory/eval · **B** backend data/integrations/security/deploy ·
**C** (Aman, repo owner) web app, voice, notifications. C also leads project weeks 1, 4 and 6.

## Layout
- `backend/` — FastAPI core plane (uv, Python 3.12). `src/helpmate/domain/ports.py` = the seams;
  `container.py` picks adapters from `HELPMATE_*` env; `agent/policy.py` = approval invariant;
  `adapters/fakes/` = a fake for every port; `eval/bench.py` = model benchmark (`helpmate-bench`).
- `services/speech/` — separate speech service on :8001 (own uv env). Fake engine today;
  real faster-whisper + kokoro-onnx is Phase 5.
- `web/` — React 19 + TS + Vite PWA. `src/api/schema.d.ts` is GENERATED; `src/mocks/` = MSW
  handlers used by `npm run dev:mock` and by all unit tests; `src/sw.ts` = service worker (push + ack).
- `contracts/openapi.yaml` — GENERATED from backend schemas; CI fails on drift.
- `infra/docker-compose.yml` — pgvector Postgres + SeaweedFS, ports bound to 127.0.0.1.

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

## Status (update as phases land)
- Done: Phase 0–2 (repo, CI, contract v0.1, walking skeleton), benchmark script, Phase 4 web
  (tasks, folders + custom fields, memory review, login/TOTP screens, settings, edit-then-approve).
- Not yet visually checked in a browser. Not yet run against real Ollama or a real phone.
- Next: Phase 3 on the GPU machine (Ollama, `ollama ps` = 100% GPU, run the benchmark, commit
  results) → Phase 5 real voice → Phase 6 Web Push → Phase 7 Tailscale. Midterm video ≈ Oct 26.
- `main` is protected (PR + review + 3 CI checks); owner can bypass while teammates aren't added yet.
