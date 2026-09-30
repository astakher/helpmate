# Model benchmark — DESKTOP-O05C1ES

- Date: 2026-09-30 16:50
- GPU: NVIDIA GeForce GTX 1050 Ti with Max-Q Design, 4096 MiB
- Ollama: 0.35.0
- Prompts: 15 seed cases x 1 run(s), temperature 0
- Pipeline: routed (improved + a no-tools classification call first, then only the chosen tool (TTFT includes the classification))

| Model | Load s | GPU % | VRAM GB | TTFT median ms | TTFT p90 ms | tok/s | Tool choice | Args valid (strict) | Args correct | Retries |
|---|---|---|---|---|---|---|---|---|---|---|
| llama3.2:3b | 0.0 | 100 | 2.55 | 1264.0 | 2119.5 | 27.8 | 93% | 100% | 100% | 0 |

Targets from the spec: text first word ≤ 1.5 s, tool choice ≥ 90 %, valid args ≥ 95 %, GPU 100 % (no CPU spill).

## Misses

**llama3.2:3b**
- `chat-explain`: called `create_task` — route=create_task

