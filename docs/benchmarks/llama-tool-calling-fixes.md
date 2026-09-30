# llama3.2:3b tool calling: what fixed it (Sep 29, XPS)

Stand-in work for Workstream A, prototyped in the testbed so A can adopt it in the agent loop.
Code: `backend/src/helpmate/agent/llm_tools.py`, `agent/when.py`; benchmark: `helpmate-bench --pipeline`.

**Setup:** Dell XPS 15, GTX 1050 Ti 4 GB, driver 582.66, **Ollama 0.35.0**, `LLAMA_ARG_FIT_TARGET=512`.
llama3.2:3b stayed at **100% GPU, 2.55 GB VRAM** in every run. Temperature 0, one run per prompt.
Two prompt sets: **seed** (15 prompts, also looked at while designing the fixes) and **held-out**
(16 new prompts, written before any improved run and never used for tuning).

## Results

| Pipeline | Set | Right tool | Args valid | Args correct | First word of a plain reply* | Until the tool call* |
|---|---|---|---|---|---|---|
| baseline (Sep 29 setup) | seed | 80% | 91% | 73% | – | 0.92 s |
| | held-out | 75% | 92% | 58% | – | 1.13 s |
| improved | seed | 73% | **100%** | **100%** | – | 1.20 s |
| | held-out | 81% | **100%** | **100%** | – | 1.42 s |
| **routed** | seed | **100%** | **100%** | **100%** | **0.46 s** | 1.53 s |
| | held-out | **94%** | **100%** | **100%** | **0.47 s** | 1.86 s |
| *Targets* | | ≥ 90% | ≥ 95% | | ≤ 1.5 s | |

\*Medians. In baseline and improved, most small-talk prompts wrongly got a tool call, so there is no
honest plain-reply number for them. `rem-at` is now scored against the *next* 5 pm (the Sep 29
report marked the right answer wrong because it ran after 5 pm), which is why seed/baseline shows
73% args correct here instead of 64%.

Reports: `desktop-o05c1es-{seed,holdout}-{baseline,improved,routed}.md` (+ `.json`) in this folder.

## What each fix did

1. **Time words resolved in code** (`agent/when.py`). The model copies "in 10 minutes", "Friday at
   3pm", "every day at 7am" into `when`, and code computes `due_at` and the RRULE (DST-safe).
   → every argument miss is gone on **both** sets: `PT10M`, wrong-day "in two hours", empty
   `recurrence`, "Friday" landing on Thursday, "in 2 days" at midnight. No retries were needed.
2. **A system prompt with a "plain reply for small talk" rule and examples** → **no effect.** With
   tools attached, llama3.2:3b called a tool for almost every chat prompt ("Thanks!" →
   `create_reminder`, "leap year?" → `create_task`) however the rule was worded.
3. **Routing** (`--pipeline routed`): first classify the message **with no tools attached**, using
   Ollama structured output (`reply | create_reminder | create_task | list_reminders`); then reply
   with no tools, or offer only the chosen tool → tool choice **100% / 94%**. The one miss:
   "Any reminders coming up?" was classified as `reply`.
4. **Clock moved to the end of the system prompt** (so Ollama can reuse its cached prefix) → no
   measurable latency change.

## Cost and trade-offs

- Routing adds one short call, about **0.3–0.4 s**, and it lands on tool requests: the approval card
  starts about 1.5–1.9 s after sending. Plain replies are *faster* (0.46 s), because they no longer
  carry the tool definitions.
- 31 prompts is still small (one miss ≈ 6 points). The spec asks for ≥ 60 before trusting the
  percentages.

## Recommendations for Workstream A

- Adopt fix 1 and fix 3 in the agent loop (`HELPMATE_AGENT=loop`): `llm_tools.specs()`,
  `system_prompt()`, `resolve()` with validate-and-retry once on `ResolveError`, and the router
  (`ROUTER_PROMPT` + `ROUTE_FORMAT`). The canonical tool schemas (policy engine, proposal cards,
  `GET /api/tools`) are unchanged, so the web app is unaffected.
- Cut the routing cost: run the deterministic `intent_parser` first and skip the router when it
  matches; only unmatched messages pay for classification.
- Improve the router on "list" phrasings ("anything coming up?", "what's scheduled?") and grow the
  golden set to ≥ 60, including more small talk that mentions reminders or tasks.
