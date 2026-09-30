# Model benchmark — DESKTOP-O05C1ES

- Date: 2026-09-29 21:19
- GPU: NVIDIA GeForce GTX 1050 Ti with Max-Q Design, 4096 MiB
- Ollama: 0.35.0
- Prompts: 16 holdout cases x 1 run(s), temperature 0
- Pipeline: improved (time words resolved in code, validate-and-retry once; see agent/llm_tools.py)

| Model | Load s | GPU % | VRAM GB | TTFT median ms | TTFT p90 ms | tok/s | Tool choice | Args valid (strict) | Args correct | Retries |
|---|---|---|---|---|---|---|---|---|---|---|
| llama3.2:3b | 0.0 | 100 | 2.55 | 1245.7 | 1715.4 | 23.3 | 81% | 100% | 100% | 0 |

Targets from the spec: text first word ≤ 1.5 s, tool choice ≥ 90 %, valid args ≥ 95 %, GPU 100 % (no CPU spill).

## Misses

**llama3.2:3b**
- `h-chat-leap`: called `create_task`
- `h-chat-about`: called `list_reminders`
- `h-chat-advice`: called `create_task`

