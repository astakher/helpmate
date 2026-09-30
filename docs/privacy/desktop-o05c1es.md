# Privacy check: DESKTOP-O05C1ES

- Date: 2026-09-30 15:47
- Watched: HelpMate API, Ollama model runner, Ollama server, Ollama tray app (updates; not inference), speech service (connections sampled every 50 ms for 9 s)
- **PASS: during the workload, HelpMate's processes talked only to this machine, your own Tailscale devices and push services.**

## Workload

- health: llm=ollama:llama3.2:3b, stt=http:http://127.0.0.1:8001
- chat "What's the capital of Canada? One sentence.": reply
- chat 'remind me to stretch in 5 minutes': proposal
- voice round trip: 'Remind me to call mom.'
- test push: no devices subscribed (Settings > Notifications > Enable)

## Remote endpoints seen

| Process | Remote | Reverse DNS | Class | Samples |
|---|---|---|---|---|
| HelpMate API | 127.0.0.1:8001 |  | loopback | 32 |
| HelpMate API | 127.0.0.1:11434 |  | loopback | 65 |
| HelpMate API | 127.0.0.1:60464 |  | loopback | 65 |
| HelpMate API | 127.0.0.1:63989 |  | loopback | 65 |
| HelpMate API | 127.0.0.1:63990 |  | loopback | 65 |
| Ollama model runner | 127.0.0.1:60469 |  | loopback | 10 |
| Ollama model runner | 127.0.0.1:60473 |  | loopback | 6 |
| Ollama model runner | 127.0.0.1:60477 |  | loopback | 7 |
| Ollama model runner | 127.0.0.1:60481 |  | loopback | 18 |
| Ollama server | 127.0.0.1:51953 |  | loopback | 1 |
| Ollama server | 127.0.0.1:54782 |  | loopback | 31 |
| Ollama server | 127.0.0.1:60465 |  | loopback | 64 |
| speech service | 127.0.0.1:60455 |  | loopback | 65 |
| speech service | 127.0.0.1:60456 |  | loopback | 65 |
| speech service | 127.0.0.1:60462 |  | loopback | 65 |
| speech service | 127.0.0.1:60482 |  | loopback | 32 |

Loopback = API <-> Ollama / speech service. Push services receive only the encrypted notification payload (title/body, or generic text with private previews on).
Sampling can miss sub-50 ms connections; for a formal run also capture with Wireshark or pktmon during the same workload.
