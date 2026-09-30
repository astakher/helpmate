# Stand-in for Workstream A - not part of the Part C deliverable
"""What the model sees, kept separate from the canonical tools in tools.py.

The canonical args models (tools.py) stay the contract: the policy engine validates them, proposal
cards store them, and GET /api/tools returns them for the web app's Edit form. The model gets
simpler, easier-to-fill versions, and `resolve()` turns its call into canonical args:

- create_reminder takes the owner's time words in `when` ("in 10 minutes", "Friday at 3pm") plus
  enum fields `repeat`/`weekday`, and when.py computes `due_at` and the RRULE in code.
- The calendar tools take time words too ("tomorrow afternoon", "Friday 2 to 4pm", "this week"),
  and search_email takes plain fields (sender, about, unread_only, days) that become a Gmail query
  here, so the model never writes dates or search syntax.
- send_email only accepts addresses the owner actually typed (`said`): a small model will happily
  invent "mom@example.com". Missing ones raise NeedsOwner, which is asked back, not retried.
- The system prompt says exactly when to use a tool and when to just reply, with examples that
  are deliberately NOT the benchmark's prompts.

Measured with `helpmate-bench --pipeline improved|routed` (vs `baseline`, the Sep 29 setup).
The real agent loop (HELPMATE_AGENT=loop) should use `specs()`, `system_prompt()` and `resolve()`,
and on `ResolveError` send the message back to the model once (validate-and-retry). "routed" adds
a no-tools classification step first (ROUTER_PROMPT + ROUTE_FORMAT, see below).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, ValidationError

from helpmate.agent.tools import CreateTaskArgs, ToolRegistry
from helpmate.agent.when import (
    RRULE_DAYS,
    WEEKDAYS,
    UnclearTime,
    parse_range,
    parse_span,
    parse_when,
)
from helpmate.domain.models import ToolSpec

DEFAULT_EVENT_MINUTES = 60


class ResolveError(ValueError):
    """The model's call can't become valid canonical args. The message is written for the model."""


class NeedsOwner(ResolveError):
    """Only the owner can fix this (e.g. an email address they didn't give). Retrying the model
    won't help, so the agent asks the owner. The message is written for the owner."""


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


class EmailSearchCall(BaseModel):
    sender: str | None = Field(
        default=None, description="Only mail from this person, company or address, e.g. 'alice'"
    )
    about: str | None = Field(default=None, description="Words the mail is about, e.g. 'invoice'")
    unread_only: bool = Field(default=False, description="Only unread / new mail")
    days: int | None = Field(default=None, description="Only mail from the last N days")


class EmailCall(BaseModel):
    to: list[str] = Field(description="Recipient email addresses, exactly as the owner typed them")
    subject: str = Field(description="A short subject line")
    body: str = Field(description="The complete email, ready to send")


class EventsCall(BaseModel):
    when: str = Field(
        description="The owner's words for the period, e.g. 'today', 'tomorrow', 'Friday', "
        "'this week', 'next week'"
    )


class EventCall(BaseModel):
    title: str = Field(description="What the event is, e.g. 'lunch with Sam'")
    when: str = Field(
        description="The owner's time words copied exactly, e.g. 'tomorrow at 3pm', "
        "'Friday 2 to 4pm'. Never convert them to a date yourself."
    )
    duration_minutes: int | None = Field(
        default=None, description="Only if the owner says how long it lasts"
    )
    location: str | None = Field(default=None, description="Only if the owner says where")


class FreeTimeCall(BaseModel):
    when: str = Field(
        default="this week",
        description="The owner's words for the period to search, e.g. 'tomorrow', 'this week'",
    )
    duration_minutes: int = Field(default=60, description="How long they need, in minutes")


_DESCRIPTIONS = {
    "create_reminder": "Set a reminder the owner asked for. It is pushed to their phone.",
    "create_task": "Add a task the owner asked for to a horizon: week (default), term, year or "
    "someday.",
    "list_reminders": "Show the owner's upcoming reminders, only when they ask what reminders "
    "they have.",
    "list_tasks": "Show the owner's open tasks, only when they ask what tasks they have.",
    "search_email": "Search the owner's email when they ask about their mail or inbox.",
    "send_email": "Write an email the owner asked for. It's sent only after they approve it.",
    "list_events": "Show what's on the owner's calendar for a day or period.",
    "create_event": "Add an event the owner asked for to their calendar.",
    "find_free_time": "Find when the owner is free for a given length of time.",
}
_LLM_ARGS: dict[str, type[BaseModel]] = {
    "create_reminder": ReminderCall,
    "search_email": EmailSearchCall,
    "send_email": EmailCall,
    "list_events": EventsCall,
    "create_event": EventCall,
    "find_free_time": FreeTimeCall,
}


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
- tell them which reminders they have -> list_reminders; which tasks -> list_tasks
- look at their email -> search_email; write or send an email -> send_email
- tell them what's on their calendar -> list_events; add something to it -> create_event
- find when they're free -> find_free_time
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


_INTRO = "You are HelpMate, a concise personal assistant running on the owner's laptop."
_TOOL_RULES = {
    "create_reminder": """Call create_reminder for the owner's message. Copy their time words into \
`when` exactly as they said them; never work out dates or times yourself. Set `repeat` only if \
they say every, each or daily.
Owner: remind me to feed the cat in 20 minutes
-> create_reminder(text="feed the cat", when="in 20 minutes")
Owner: every Tuesday at 6pm remind me to take the bins out
-> create_reminder(text="take the bins out", when="6pm", repeat="weekly", weekday="tuesday")""",
    "create_task": """Call create_task for the owner's message. `horizon` is week (the default), \
term, year or someday.
Owner: add book the dentist to this term
-> create_task(title="book the dentist", horizon="term")""",
    "list_reminders": "Call list_reminders.",
    "list_tasks": """Call list_tasks. Set `horizon` only if the owner names one: week, term, \
year or someday.
Owner: what's on my list for this term?
-> list_tasks(horizon="term")""",
    "search_email": """Call search_email for the owner's message. Fill only the fields they \
mention; leave the rest out.
Owner: anything new from the bank?
-> search_email(sender="bank", unread_only=true)
Owner: find the email about the field trip form from last week
-> search_email(about="field trip form", days=7)""",
    "send_email": """Call send_email for the owner's message. Use only email addresses the owner \
wrote; never make one up. Write the whole email in `body`, friendly and short, in the owner's \
voice, without a signature name.
Owner: email jo@example.com to say I'll be 10 minutes late
-> send_email(to=["jo@example.com"], subject="Running late", body="Hi Jo, I'm running about \
10 minutes late. See you soon!")""",
    "list_events": """Call list_events. Copy the owner's words for the day or period into \
`when`.
Owner: what have I got on Thursday?
-> list_events(when="Thursday")""",
    "create_event": """Call create_event for the owner's message. Copy their time words into \
`when` exactly; never work out dates yourself. Set `duration_minutes` only if they say how long.
Owner: put lunch with Sam on my calendar tomorrow at 12:30
-> create_event(title="lunch with Sam", when="tomorrow at 12:30")
Owner: book the gym Saturday 10 to 11:30am
-> create_event(title="gym", when="Saturday 10 to 11:30am")""",
    "find_free_time": """Call find_free_time. Copy the owner's words for the period into `when` \
and put how long they need in `duration_minutes`.
Owner: when am I free for two hours next week?
-> find_free_time(when="next week", duration_minutes=120)""",
}


def tool_prompt(name: str, now: datetime, tz: ZoneInfo) -> str:
    """For a routed call: only the chosen tool's rules and examples (a 3B model copes better with
    one tool's instructions than with all of them), clock last as in system_prompt()."""
    local = now.astimezone(tz)
    rules = _TOOL_RULES.get(name, f"Call {name} for the owner's message.")
    return f"{_INTRO}\n\n{rules}\n\nNow: {local:%A %Y-%m-%d %H:%M} ({tz.key})."


def reply_prompt(now: datetime, tz: ZoneInfo) -> str:
    """For plain replies after routing (no tools attached). Deliberately has no example replies:
    the tool prompt's "Good morning!" example was echoed back to "thanks, you're great"."""
    local = now.astimezone(tz)
    return (
        "You are HelpMate, a friendly, concise personal assistant running on the owner's laptop. "
        "Answer the owner's message directly in at most three sentences. You can set reminders, "
        "add tasks, search and send email and manage their calendar when they ask; there's no "
        "need to offer that every time. "
        f"Now: {local:%A %Y-%m-%d %H:%M} ({tz.key})."
    )


# --- Routing (pipeline "routed") -------------------------------------------------------------
# Measured Sep 29: with tools attached, llama3.2:3b called a tool for every small-talk prompt no
# matter what the system prompt said. So step 1 classifies the message with NO tools attached,
# using Ollama structured output; step 2 either replies without tools or offers only that tool.

ROUTES = (
    "reply",
    "create_reminder",
    "create_task",
    "list_reminders",
    "list_tasks",
    "search_email",
    "send_email",
    "list_events",
    "create_event",
    "find_free_time",
)
_ROUTE_RULES = {
    "create_reminder": "they ask to be reminded of something",
    "create_task": "they ask to add something to their tasks or to-do list",
    "list_reminders": "they ask which reminders they have",
    "list_tasks": "they ask to see which tasks or to-dos they have",
    "search_email": "they want to see, read, check or search their email, mail, inbox or "
    "messages: the latest mail, new mail, mail from someone or about something",
    "send_email": "they ask to write, draft, send or reply to an email",
    "list_events": "they ask what is on their calendar or schedule, or about their meetings or "
    "events",
    "create_event": "they ask to put an event, meeting or appointment on their calendar, or to "
    "book or schedule one",
    "find_free_time": "they ask when they are free or available, or to find time for something",
}
_REPLY_RULE = """- "reply": anything else: greetings, thanks, small talk, questions, maths, \
explanations, advice, jokes. Also "reply" when they only talk about reminders, tasks, email or \
their calendar without asking you to do something, or say not to do something."""

# Topic words. Measured Sep 30 (a live miss): llama3.2:3b sends "show me …" to whichever list
# route it sees first, whatever follows ("show me the last mail" -> list_reminders, and once
# list_tasks existed, -> list_tasks). But people asking for these tools name the topic: every
# reminder (17), task (10) and email (9) prompt in the three golden sets contains one of these
# words. Without one, the routes aren't offered at all: not in the prompt (dropping them only from
# the enum made the model finish "list_" as another list route) and not in the schema. Calendar
# requests are too varied ("am I free Friday?", "what have I got on Thursday?") to guard this way.
_REMINDER_WORDS = re.compile(r"\bremind|\b(?:ping|nudge|alert) me\b", re.IGNORECASE)
_TASK_WORDS = re.compile(r"\btasks?\b|\bto-?dos?\b|\bto do\b|\blist\b", re.IGNORECASE)
_MAIL_WORDS = re.compile(r"mail|inbox|\bmessages?\b|@", re.IGNORECASE)
_ROUTE_NEEDS = {
    "create_reminder": _REMINDER_WORDS,
    "list_reminders": re.compile(r"\bremind", re.IGNORECASE),
    "create_task": _TASK_WORDS,
    "list_tasks": _TASK_WORDS,
    "search_email": _MAIL_WORDS,
    "send_email": _MAIL_WORDS,
}


def routes_for(text: str) -> tuple[str, ...]:
    """The routes this message can plausibly take (see _ROUTE_NEEDS)."""
    return tuple(r for r in ROUTES if (need := _ROUTE_NEEDS.get(r)) is None or need.search(text))


def router_prompt(routes: tuple[str, ...] = ROUTES) -> str:
    lines = [f'- "{r}": {_ROUTE_RULES[r]}' for r in routes if r in _ROUTE_RULES]
    return (
        "Classify the owner's message for a personal assistant. Answer only with JSON "
        '{"action": "..."}.\n' + "\n".join(lines) + "\n" + _REPLY_RULE
    )


def route_format(routes: tuple[str, ...] = ROUTES) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"action": {"type": "string", "enum": list(routes)}},
        "required": ["action"],
    }


ROUTER_PROMPT = router_prompt()
ROUTE_FORMAT = route_format()


def parse_route(content: str, routes: tuple[str, ...] = ROUTES) -> str:
    """The router's JSON -> a route; anything unexpected falls back to a plain reply."""
    try:
        action = json.loads(content).get("action")
    except (json.JSONDecodeError, AttributeError):
        return "reply"
    return action if action in routes else "reply"


_PLACEHOLDERS = {"", "null", "none", "nil", "n/a", "na", "undefined", "unknown"}


def _placeholder(value: Any) -> bool:
    """llama3.2:3b fills fields it doesn't need with the *string* "null" (live, Sep 30: "show me
    the last mail" searched `from:null null`). Such values mean "not given"."""
    return value is None or (isinstance(value, str) and value.strip().lower() in _PLACEHOLDERS)


def resolve(
    name: str,
    arguments: dict[str, Any],
    tools: ToolRegistry,
    now: datetime,
    tz: ZoneInfo,
    said: str | None = None,
) -> dict[str, Any]:
    """The model's call -> canonical args (JSON-ready), validated. Raises ResolveError.
    `said` is the owner's message: send_email recipients must appear in it."""
    tool = tools.get(name)
    if tool is None:
        raise ResolveError(f"There is no tool called {name!r}. Reply in plain text instead.")
    arguments = {k: v for k, v in arguments.items() if not _placeholder(v)}
    try:
        if name == "create_reminder":
            arguments = _reminder_args(arguments, now, tz)
        elif name == "create_task":
            arguments = _task_args(arguments)
        elif name == "list_tasks":
            arguments = {k: v for k, v in _task_args(arguments).items() if k == "horizon"}
        elif name == "search_email":
            arguments = _search_args(arguments)
        elif name == "send_email":
            arguments = _email_args(arguments, said)
        elif name in ("list_events", "find_free_time"):
            arguments = _period_args(name, arguments, now, tz)
        elif name == "create_event":
            arguments = _event_args(arguments, now, tz)
    except UnclearTime as exc:
        raise ResolveError(f"{name}: {exc}") from exc
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


def _search_args(arguments: dict[str, Any]) -> dict[str, Any]:
    if arguments.get("query"):  # the canonical shape
        return {"query": str(arguments["query"])}
    terms = []
    if sender := str(arguments.get("sender") or "").strip():
        terms.append(f'from:"{sender}"' if " " in sender else f"from:{sender}")
    if about := str(arguments.get("about") or "").strip():
        terms.append(about)
    if arguments.get("unread_only") in (True, "true"):
        terms.append("is:unread")
    days = arguments.get("days")
    if isinstance(days, int | str) and str(days).isdigit() and int(days) > 0:
        terms.append(f"newer_than:{int(days)}d")
    return {"query": " ".join(terms)}


_ADDRESS = re.compile(r"[^@\s<>,;()\[\]\"']+@[^@\s<>,;()\[\]\"']+\.[a-z]{2,}", re.IGNORECASE)


def _email_args(arguments: dict[str, Any], said: str | None) -> dict[str, Any]:
    def addresses(value: Any) -> list[str]:
        items = value if isinstance(value, list) else [value] if value else []
        return [a.lower().rstrip(".") for item in items for a in _ADDRESS.findall(str(item))]

    to, cc = addresses(arguments.get("to")), addresses(arguments.get("cc"))
    typed = {a.lower().rstrip(".") for a in _ADDRESS.findall(said)} if said is not None else None
    if typed is not None:
        to, cc = [a for a in to if a in typed], [a for a in cc if a in typed]
        if not to and typed:
            to = sorted(typed)  # the model dropped or mangled the address the owner gave
    if not to:
        raise NeedsOwner(
            "Who should I send it to? Please include their email address, "
            "e.g. 'email jo@example.com to say I'm running late'."
        )
    return {
        "to": to,
        "cc": cc,
        "subject": arguments.get("subject") or "",
        "body": arguments.get("body") or "",
    }


def _period_args(
    name: str, arguments: dict[str, Any], now: datetime, tz: ZoneInfo
) -> dict[str, Any]:
    if arguments.get("start") and arguments.get("end"):  # the canonical shape
        return arguments
    default = "today" if name == "list_events" else "this week"
    start, end = parse_range(str(arguments.get("when") or default), now, tz)
    args: dict[str, Any] = {"start": start.isoformat(), "end": end.isoformat()}
    if name == "find_free_time":
        args["duration_minutes"] = arguments.get("duration_minutes") or 60
    return args


def _event_args(arguments: dict[str, Any], now: datetime, tz: ZoneInfo) -> dict[str, Any]:
    if arguments.get("start") and arguments.get("end"):  # the canonical shape
        return arguments
    start, end = parse_span(str(arguments.get("when") or arguments.get("start") or ""), now, tz)
    if end is None:
        minutes = arguments.get("duration_minutes")
        minutes = int(minutes) if str(minutes or "").isdigit() and int(minutes) > 0 else None
        end = start + timedelta(minutes=minutes or DEFAULT_EVENT_MINUTES)
    return {
        "title": arguments.get("title") or "",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "location": arguments.get("location") or None,
        "description": arguments.get("description") or None,
    }


def _task_args(arguments: dict[str, Any]) -> dict[str, Any]:
    known = set(CreateTaskArgs.model_fields)
    args = {k: v for k, v in arguments.items() if k in known and v not in (None, "")}
    if isinstance(args.get("horizon"), str):
        args["horizon"] = args["horizon"].strip().lower().removeprefix("this ")
        if args["horizon"] in ("all", "any", "none"):  # "all my tasks": no filter
            del args["horizon"]
    return args
