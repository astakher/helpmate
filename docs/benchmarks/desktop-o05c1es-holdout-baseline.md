# Model benchmark — DESKTOP-O05C1ES

- Date: 2026-09-29 21:16
- GPU: NVIDIA GeForce GTX 1050 Ti with Max-Q Design, 4096 MiB
- Ollama: 0.35.0
- Prompts: 16 holdout cases x 1 run(s), temperature 0
- Pipeline: baseline (model writes ISO datetimes itself, no retry)

| Model | Load s | GPU % | VRAM GB | TTFT median ms | TTFT p90 ms | tok/s | Tool choice | Args valid (strict) | Args correct | Retries |
|---|---|---|---|---|---|---|---|---|---|---|
| llama3.2:3b | 0.0 | 100 | 2.55 | 1349.8 | 1455.0 | 27.1 | 75% | 92% | 58% | 0 |

Targets from the spec: text first word ≤ 1.5 s, tool choice ≥ 90 %, valid args ≥ 95 %, GPU 100 % (no CPU spill).

## Misses

**llama3.2:3b**
- `h-rem-45`: called `create_reminder` — strict: Input should be a valid datetime or date, input is too short; due_at='PT45M', expected ~22:00
- `h-rem-hour`: called `create_reminder` — due_at='2026-09-30T21:15:00-04:00', expected ~22:15
- `h-rem-daily`: called `create_reminder` — recurrence='' lacks 'DAILY'
- `h-rem-friday`: called `create_reminder` — due_at='2026-10-01T15:00:00-04:00', expected Fri 2026-10-02 15:00
- `h-rem-days`: called `create_reminder` — due_at='2026-09-30T00:00:00-04:00', expected ~21:15
- `h-chat-thanks`: called `create_reminder`
- `h-chat-leap`: called `create_task`
- `h-chat-about`: called `create_reminder`
- `h-chat-advice`: called `create_task`

