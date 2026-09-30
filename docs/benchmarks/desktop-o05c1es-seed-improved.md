# Model benchmark — DESKTOP-O05C1ES

- Date: 2026-09-29 21:19
- GPU: NVIDIA GeForce GTX 1050 Ti with Max-Q Design, 4096 MiB
- Ollama: 0.35.0
- Prompts: 15 seed cases x 1 run(s), temperature 0
- Pipeline: improved (time words resolved in code, validate-and-retry once; see agent/llm_tools.py)

| Model | Load s | GPU % | VRAM GB | TTFT median ms | TTFT p90 ms | tok/s | Tool choice | Args valid (strict) | Args correct | Retries |
|---|---|---|---|---|---|---|---|---|---|---|
| llama3.2:3b | 0.0 | 100 | 2.55 | 1083.0 | 1730.3 | 26.4 | 73% | 100% | 100% | 0 |

Targets from the spec: text first word ≤ 1.5 s, tool choice ≥ 90 %, valid args ≥ 95 %, GPU 100 % (no CPU spill).

## Misses

**llama3.2:3b**
- `chat-greeting`: called `list_reminders`
- `chat-fact`: called `list_reminders`
- `chat-explain`: called `list_reminders`
- `chat-negation`: called `list_reminders`

