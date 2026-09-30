# Model benchmark — DESKTOP-O05C1ES

- Date: 2026-09-29 20:35
- GPU: NVIDIA GeForce GTX 1050 Ti with Max-Q Design, 4096 MiB
- Ollama: 0.34.4
- Prompts: 15 seed cases x 1 run(s), temperature 0

| Model | Load s | GPU % | VRAM GB | TTFT median ms | TTFT p90 ms | tok/s | Tool choice | Args valid (strict) | Args correct |
|---|---|---|---|---|---|---|---|---|---|
| llama3.2:3b | 6.0 | 100 | 2.55 | 901.0 | 1575.9 | 25.1 | 80% | 91% | 64% |
| qwen3:4b | 11.3 | 84 | 2.96 | 1638.4 | 1727.3 | 15.2 | 100% | 100% | 100% |

Targets from the spec: text first word ≤ 1.5 s, tool choice ≥ 90 %, valid args ≥ 95 %, GPU 100 % (no CPU spill).

## Misses

**llama3.2:3b**
- `rem-at`: called `create_reminder` — due_at='2026-09-30T17:00:00-04:00', expected 2026-09-29 17:00
- `rem-in`: called `create_reminder` — strict: Input should be a valid datetime or date, input is too short; due_at='PT10M', expected ~20:33
- `rem-hours`: called `create_reminder` — due_at='2026-09-30T18:00:00-04:00', expected ~22:23
- `rem-recurring`: called `create_reminder` — recurrence='' lacks 'MO'
- `chat-greeting`: called `list_reminders`
- `chat-fact`: called `list_reminders`
- `chat-explain`: called `list_reminders`

