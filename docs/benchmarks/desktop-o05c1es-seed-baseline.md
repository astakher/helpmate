# Model benchmark — DESKTOP-O05C1ES

- Date: 2026-09-29 21:15
- GPU: NVIDIA GeForce GTX 1050 Ti with Max-Q Design, 4096 MiB
- Ollama: 0.35.0
- Prompts: 15 seed cases x 1 run(s), temperature 0
- Pipeline: baseline (model writes ISO datetimes itself, no retry)

| Model | Load s | GPU % | VRAM GB | TTFT median ms | TTFT p90 ms | tok/s | Tool choice | Args valid (strict) | Args correct | Retries |
|---|---|---|---|---|---|---|---|---|---|---|
| llama3.2:3b | 14.2 | 100 | 2.55 | 810.1 | 1406.4 | 27.8 | 80% | 91% | 73% | 0 |

Targets from the spec: text first word ≤ 1.5 s, tool choice ≥ 90 %, valid args ≥ 95 %, GPU 100 % (no CPU spill).

## Misses

**llama3.2:3b**
- `rem-in`: called `create_reminder` — strict: Input should be a valid datetime or date, input is too short; due_at='PT10M', expected ~21:25
- `rem-hours`: called `create_reminder` — due_at='2026-09-30T17:15:00-04:00', expected ~23:15
- `rem-recurring`: called `create_reminder` — recurrence='' lacks 'MO'
- `chat-greeting`: called `list_reminders`
- `chat-fact`: called `list_reminders`
- `chat-explain`: called `list_reminders`

