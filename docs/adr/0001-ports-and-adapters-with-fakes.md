# ADR 0001 — Ports and adapters, with a fake for every seam

**Status:** accepted (week 1)

## Context
Three people build three workstreams in parallel: A (agent/LLM/memory), B (data/integrations/security) and C (web/voice/notifications). The web app can't wait for the agent loop, and the agent loop can't wait for Postgres. We also need to swap models and connectors, and to unit-test with a simulated clock.

## Decision
- Each external dependency is a `Protocol` in `domain/ports.py`: LLM, embeddings, repositories, scheduler, notifier, STT, TTS, mail, calendar and files.
- Each port gets a **fake** adapter in week 1. `container.py` picks the adapter from `HELPMATE_*` env vars.
- A shared contract test suite per port runs against the fake and every real adapter.
- The web app develops against MSW mocks generated from `contracts/openapi.yaml`, and against the real backend running its fakes.

## Consequences
- A walking skeleton runs end to end on day 1 on any laptop, with no GPU.
- Each member plugs in by implementing a port and flipping one env var. The other members' code stays the same.
- The cost is keeping the fakes honest. The contract tests enforce that, and some behaviour can't be faked well (Postgres `SKIP LOCKED` job claiming), so it is tested only against the real thing.
