# Stand-in for Workstream A - not part of the Part C deliverable
"""What the model sees, kept separate from the canonical tools in tools.py.

The canonical args models (tools.py) stay the contract: the policy engine validates them, proposal
cards store them, and GET /api/tools returns them for the web app's Edit form. The model gets
simpler, easier-to-fill versions, and `resolve()` turns its call into canonical args:

- create_reminder takes the owner's time words in `when` ("in 10 minutes", "Friday at 3pm") plus
  enum fields `repeat`/`weekday`, and when.py computes `due_at` and the RRULE in code.
- The system prompt says exactly when to use a tool and when to just reply, with examples that
  are deliberately NOT the benchmark's prompts.

Measured with `helpmate-bench --pipeline improved|routed` (vs `baseline`, the Sep 29 setup).
The real agent loop (HELPMATE_AGENT=loop) should use `specs()`, `system_prompt()` and `resolve()`,
and on `ResolveError` send the message back to the model once (validate-and-retry). "routed" adds
a no-tools classification step first (ROUTER_PROMPT + ROUTE_FORMAT, see below).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, ValidationError

from helpmate.agent.tools import CreateTaskArgs, ToolRegistry
from helpmate.agent.when import RRULE_DAYS, WEEKDAYS, UnclearTime, parse_when
from helpmate.domain.models import ToolSpec


class ResolveError(ValueError):
    """The model's call can't become valid canonical args. The message is written for the model."""


Weekday = Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


class ReminderCall(BaseModel):
    text: str = Field(
        description="What to remind the owner about, without the time words, e.g. 'call mom'"
    )
    when: str = Field(
        description="The owner's time words copied exactly, e.g. 'in 10 minutes', 'at 5pm', "
        "'tomorrow at 9am', 'Friday at 3pm'. Never convert them to a date yourself."
    )
    repeat: Literal["none", "daily", "weekdays", "weekly"] = Field(
        default="none", description="Only when the owner says every / each / daily"
    )
    weekday: Weekday | None = Field(default=None, description="For repeat=weekly: which day")


_DESCRIPTIONS = {
    "create_reminder": "Set a reminder the owner asked for. It is pushed to their phone.",
    "create_task": "Add a task the owner asked for to a horizon: week (default), term, year or "
    "someday.",
    "list_reminders": "Show the owner's upcoming reminders, only when they ask what reminders "
    "they have.",
}
_LLM_ARGS: dict[str, type[BaseModel]] = {"create_reminder": ReminderCall}


def specs(tools: ToolRegistry) -> list[ToolSpec]:
    return [
        ToolSpec(
            name=tool.name,
            description=_DESCRIPTIONS.get(tool.name, tool.description),
            parameters=_LLM_ARGS.get(tool.name, tool.args_model).model_json_schema(),
        )
        for tool in tools.all()
    ]


def system_prompt(now: datetime, tz: ZoneInfo) -> str:
    # The clock goes LAST: Ollama reuses its cache for the longest unchanged prefix, so a time
    # at the top would make the whole prompt be re-read every minute.
    local = now.astimezone(tz)
    return f"""You are HelpMate, a concise personal assistant running on the owner's laptop.

Call a tool ONLY when the owner asks you to:
- remind them of something -> create_reminder
- add something to their tasks or list -> create_task
- tell them which reminders they have -> list_reminders
For everything else (greetings, thanks, small talk, general knowledge, maths, explanations, \
jokes, questions about how something works) reply in plain text and call NO tool. If the owner \
says not to do something, don't do it.

create_reminder: copy the owner's time words into `when` exactly as they said them. Never work \
out dates or times yourself. Set `repeat` only if they say every, each or daily.
create_task: `horizon` is week (the default), term, year or someday.

Examples:
Owner: remind me to feed the cat in 20 minutes
-> create_reminder(text="feed the cat", when="in 20 minutes")
Owner: every Tuesday at 6pm remind me to take the bins out
-> create_reminder(text="take the bins out", when="6pm", repeat="weekly", weekday="tuesday")
Owner: add book the dentist to this term
-> create_task(title="book the dentist", horizon="term")
Owner: good morning!
-> plain reply: Good morning! What can I do for you?
Owner: what's 12 times 12?
-> plain reply: 144.

Now: {local:%A %Y-%m-%d %H:%M} ({tz.key})."""


def reply_prompt(now: datetime, tz: ZoneInfo) -> str:
    """For plain replies after routing (no tools attached). Deliberately has no example replies:
    the tool prompt's "Good morning!" example was echoed back to "thanks, you're great"."""
    local = now.astimezone(tz)
    return (
        "You are HelpMate, a friendly, concise personal assistant running on the owner's laptop. "
        "Answer the owner's message directly in at most three sentences. You can set reminders, "
        "add tasks and list reminders when they ask; there's no need to offer that every time. "
        f"Now: {local:%A %Y-%m-%d %H:%M} ({tz.key})."
    )


# --- Routing (pipeline "routed") -------------------------------------------------------------
# Measured Sep 29: with tools attached, llama3.2:3b called a tool for every small-talk prompt no
# matter what the system prompt said. So step 1 classifies the message with NO tools attached,
# using Ollama structured output; step 2 either replies without tools or offers only that tool.

ROUTES = ("reply", "create_reminder", "create_task", "list_reminders")
ROUTE_FORMAT = {
    "type": "object",
    "properties": {"action": {"type": "string", "enum": list(ROUTES)}},
    "required": ["action"],
}
ROUTER_PROMPT = """Classify the owner's message for a personal assistant. Answer only with JSON \
{"action": "..."}.
- "create_reminder": they ask to be reminded of something
- "create_task": they ask to add something to their tasks or list
- "list_reminders": they ask which reminders they have
- "reply": anything else: greetings, thanks, small talk, questions, maths, explanations, advice, \
jokes. Also "reply" when they only mention reminders or tasks without asking for one, or say not \
to do something."""


def parse_route(content: str) -> str:
    """The router's JSON -> a route; anything unexpected falls back to a plain reply."""
    try:
        action = json.loads(content).get("action")
    except (json.JSONDecodeError, AttributeError):
        return "reply"
    return action if action in ROUTES else "reply"


def resolve(
    name: str, arguments: dict[str, Any], tools: ToolRegistry, now: datetime, tz: ZoneInfo
) -> dict[str, Any]:
    """The model's call -> canonical args (JSON-ready), validated. Raises ResolveError."""
    tool = tools.get(name)
    if tool is None:
        raise ResolveError(f"There is no tool called {name!r}. Reply in plain text instead.")
    if name == "create_reminder":
        arguments = _reminder_args(arguments, now, tz)
    elif name == "create_task":
        arguments = _task_args(arguments)
    try:
        return tool.args_model.model_validate(arguments).model_dump(mode="json")
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        raise ResolveError(f"Invalid arguments for {name}: {problems}.") from exc


def _reminder_args(arguments: dict[str, Any], now: datetime, tz: ZoneInfo) -> dict[str, Any]:
    # tolerate the canonical shape too (a model that sends due_at out of habit)
    words = arguments.get("when") or arguments.get("due_at") or ""
    weekday = arguments.get("weekday") or None
    if weekday is not None and str(weekday).lower() not in WEEKDAYS:
        raise ResolveError(f"weekday must be one of {', '.join(WEEKDAYS)}.")
    try:
        when = parse_when(str(words), now, tz, weekday=weekday)
    except UnclearTime as exc:
        raise ResolveError(f"create_reminder: {exc}") from exc

    repeat = arguments.get("repeat") or "none"
    recurrence = when.recurrence or arguments.get("recurrence") or None
    if repeat == "daily":
        recurrence = "FREQ=DAILY"
    elif repeat == "weekdays":
        recurrence = "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"
    elif repeat == "weekly":
        day = str(weekday).lower() if weekday else WEEKDAYS[when.due_at.weekday()]
        recurrence = f"FREQ=WEEKLY;BYDAY={RRULE_DAYS[WEEKDAYS.index(day)]}"
    elif repeat != "none":
        raise ResolveError("repeat must be none, daily, weekdays or weekly.")
    return {
        "text": arguments.get("text", ""),
        "due_at": when.due_at.isoformat(),
        "recurrence": recurrence,
    }


def _task_args(arguments: dict[str, Any]) -> dict[str, Any]:
    known = set(CreateTaskArgs.model_fields)
    args = {k: v for k, v in arguments.items() if k in known and v not in (None, "")}
    if isinstance(args.get("horizon"), str):
        args["horizon"] = args["horizon"].strip().lower().removeprefix("this ")
    return args
