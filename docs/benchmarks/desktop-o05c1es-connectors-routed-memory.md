# Model benchmark — DESKTOP-O05C1ES

- Date: 2026-10-01 11:30
- GPU: NVIDIA GeForce GTX 1050 Ti with Max-Q Design, 4096 MiB
- Ollama: 0.35.0
- Prompts: 26 connectors cases x 1 run(s), temperature 0
- Pipeline: routed (improved + a no-tools classification call first, then only the chosen tool (TTFT includes the classification))

| Model | Load s | GPU % | VRAM GB | TTFT median ms | TTFT p90 ms | tok/s | Tool choice | Args valid (strict) | Args correct | Retries |
|---|---|---|---|---|---|---|---|---|---|---|
| llama3.2:3b | 0.0 | 100 | 2.55 | 1606.6 | 2415.0 | 27.7 | 92% | 100% | 100% | 0 |

Targets from the spec: text first word ≤ 1.5 s, tool choice ≥ 90 %, valid args ≥ 95 %, GPU 100 % (no CPU spill).

## Misses

**llama3.2:3b**
- `chat-mail-talk`: called `send_email` — route=send_email
- `mail-newest-message`: called `None` — route=reply

