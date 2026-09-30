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

## Update Sep 30: nine routes (Gmail + Google Calendar)

The router now picks from nine actions: `reply`, the three reminder/task tools, and `search_email`,
`send_email`, `list_events`, `create_event`, `find_free_time`. Two further changes shipped with them:

- **One tool's rules per routed call** (`llm_tools.tool_prompt()`): once the router has chosen, the
  model sees only that tool's rules and examples, not all nine. `system_prompt()` is still used by
  the `improved` pipeline.
- **The same "words in, code does the work" idea for the new tools**: calendar tools take the owner's
  time words ("Friday 2 to 4pm", "this week") and `when.py` turns them into exact times.
  `search_email` takes sender / about / unread_only / days, and code builds the Gmail query.
  `send_email` only accepts addresses the owner typed; otherwise the agent asks who it's for
  (`NeedsOwner`, not retried).

New case set `golden_connectors.jsonl` (18 prompts: email, calendar, and look-alikes that must *not*
use them, e.g. "remind me about the dentist…", "add 'email the landlord' to my to-do list"). It was
written before the first run.

| Run | Seed (15) | Held-out (16) | Connectors (18) | Args valid / correct |
|---|---|---|---|---|
| Sep 29, four routes | 100% | 94% | – | 100% / 100% |
| Sep 30, nine routes (first run) | 93% | **100%** | **94%** | 100% / 100% |
| Sep 30, nine routes + "only talks about email or calendar → reply" | 93% | **100%** | **94%** | 100% / 100% |

All runs: llama3.2:3b, 100% GPU, 2.55 GB VRAM, no retries needed. Seed + held-out together stayed at
30/31. The misses are both "talks about it without asking":

- `chat-explain` "Explain the PARA method for organizing notes" → `create_task`. That makes a card
  the owner has to approve, so nothing is written.
- `chat-mail-talk` "I get way too many emails these days" → `send_email` in the first run. The
  address guard stopped it and the agent asked who to send to. After the rule tweak it went to
  `search_email` (read-only) instead, which is why the tweak was kept even though the score didn't
  move. The connectors set informed that tweak, so it is **no longer held out**.

Reports: `desktop-o05c1es-{seed,holdout,connectors}-routed-9routes[-v2].md`.

Live on the XPS through chat (real Google account, read-only): "what's on my calendar this week?",
"any unread emails?" and "when am I free for an hour tomorrow?" each chose the right tool, and each
answered in ~2 s once the model was warm.

## Update Sep 30 (evening): a live miss, "show me the last mail"

Typed into the app, it was answered with "You have no upcoming reminders." Two separate bugs:

1. **Routing: "show me …" goes to the first list route**, whatever follows ("show me the last
   mail" → `list_reminders`; once `list_tasks` existed, → `list_tasks`). Fix: **topic words**
   (`llm_tools.routes_for`). People asking for reminders, tasks or email name the topic, and every
   such prompt in the golden sets (17 reminder, 10 task, 9 email) does. Without one of the words,
   those routes are left out of both the router prompt and its schema. Leaving them out of the
   schema alone doesn't work: the model then finishes `list_` as another list route. Calendar
   routes aren't guarded ("am I free Friday?" names no topic).
2. **Arguments: the model writes the string `"null"`** for fields it doesn't need, so the search
   became `from:null null` ("No emails match."). The old check only asked that the query
   *contain* `is:unread`, so the benchmark passed it. Fix: `resolve()` drops placeholder values
   ("null", "none", "n/a", …) for every tool, and a new `field!~` check fails any query that
   contains "null".

Also new: a read-only `list_tasks` tool ("show me my tasks" had nowhere right to go).

| Run | Seed (15) | Held-out (16) | Connectors | Args valid / correct |
|---|---|---|---|---|
| nine routes + "talks about → reply" (above) | 93% | 100% | 94% (18) | 100% / 100% |
| + topic words, `list_tasks`, placeholders | **100%** | **100%** | **91% (23)** | 100% / 100% |

The connectors set grew by five cases: the live prompt and four like it (`live-*`, `mail-newest-message`,
`tasks-year`). Remaining misses: "I get way too many emails" → `send_email` (the agent asks who
it's for; nothing is drafted), and "read my newest message" → plain reply. Reports:
`desktop-o05c1es-{seed,holdout,connectors}-routed-guard.md`. Live after the fix: "show me the last
mail" and "check my inbox" list the latest 5, "any new emails?" searches `is:unread`, ~2 s each.
