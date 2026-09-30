"""Typed tools the agent can call.

A tool is a pydantic args model plus an async `execute`. `read_only` tools run immediately;
every other tool goes through the policy engine and becomes a Proposal first.
Workstream A adds tools here (file_item, …); B's connectors (MailPort, CalendarPort) back the
mail and calendar tools, which work the same against the fakes and against Google.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Annotated, Any, Self
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, Field, StringConstraints, model_validator

from helpmate.agent.free_time import conflicts, free_slots, is_all_day
from helpmate.domain.models import (
    CalendarEvent,
    EmailDraft,
    Horizon,
    Reminder,
    ReminderStatus,
    Risk,
    Task,
    ToolSpec,
    new_id,
)
from helpmate.domain.ports import CalendarPort, Clock, MailPort, Repositories, SchedulerPort


@dataclass(frozen=True)
class ToolDeps:
    repos: Repositories
    scheduler: SchedulerPort
    clock: Clock
    tz: ZoneInfo
    mail: MailPort
    calendar: CalendarPort
    day_hours: tuple[int, int] = (9, 18)  # local hours find_free_time may offer


@dataclass(frozen=True)
class Tool[A: BaseModel]:
    name: str
    description: str
    args_model: type[A]
    read_only: bool
    describe: Callable[[A, ZoneInfo], tuple[str, str]]  # -> (card title, card summary)
    execute: Callable[[A, ToolDeps], Awaitable[str]]  # -> human-readable result
    risk: Risk = Risk.WRITE
    preview: Callable[[A], str | None] | None = None  # e.g. full email body for the card
    check: Callable[[A, ToolDeps], Awaitable[list[str]]] | None = None  # -> card warnings

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            parameters=self.args_model.model_json_schema(),
        )


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool[Any]] = {}

    def register(self, tool: Tool[Any]) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool {tool.name!r} already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool[Any] | None:
        return self._tools.get(name)

    def all(self) -> list[Tool[Any]]:
        return list(self._tools.values())

    def specs(self) -> list[ToolSpec]:
        return [t.spec() for t in self._tools.values()]

    def __contains__(self, name: object) -> bool:
        return name in self._tools


def fmt_local(when: datetime, tz: ZoneInfo) -> str:
    return when.astimezone(tz).strftime("%a %b %d at %H:%M")


def fmt_span(start: datetime, end: datetime, tz: ZoneInfo) -> str:
    """'Tue Oct 06 14:00-15:30'. Whole days read 'Tue Oct 06' or 'Mon Oct 05 - Sun Oct 11'."""
    start, end = start.astimezone(tz), end.astimezone(tz)
    if start.time() == time(0) and end.time() == time(0):
        last = end.date() - timedelta(days=1)
        return f"{start:%a %b %d}" + ("" if last == start.date() else f" - {last:%a %b %d}")
    if end.date() == start.date() or (end.time() == time(0) and end - start <= timedelta(days=1)):
        return f"{start:%a %b %d %H:%M}-{end:%H:%M}"
    if end.time() == time(0):  # "until the end of Sunday"
        return f"{start:%a %b %d %H:%M} - {end.date() - timedelta(days=1):%a %b %d}"
    return f"{start:%a %b %d %H:%M} - {end:%a %b %d %H:%M}"


class _Period(BaseModel):
    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.end <= self.start:
            raise ValueError("end must be after start")
        if self.end - self.start > timedelta(days=31):
            raise ValueError("a period can be at most 31 days")
        return self


# --- create_reminder -------------------------------------------------------------------------


class CreateReminderArgs(BaseModel):
    text: str = Field(min_length=1, max_length=500, description="What to remind the owner about")
    due_at: AwareDatetime = Field(description="When to remind, ISO 8601 with a UTC offset")
    recurrence: str | None = Field(default=None, description="Optional RFC 5545 RRULE")


async def _create_reminder(args: CreateReminderArgs, deps: ToolDeps) -> str:
    reminder = Reminder(
        id=new_id(),
        text=args.text,
        due_at=args.due_at.astimezone(UTC),
        recurrence=args.recurrence,
        created_at=deps.clock.now(),
    )
    await deps.repos.reminders.add(reminder)
    await deps.scheduler.schedule(reminder)
    return f"Reminder set for {fmt_local(reminder.due_at, deps.tz)}."


def _describe_reminder(args: CreateReminderArgs, tz: ZoneInfo) -> tuple[str, str]:
    summary = fmt_local(args.due_at, tz)
    if args.recurrence:
        summary += f", repeating ({args.recurrence})"
    return f"Reminder: {args.text}", summary


# --- create_task -----------------------------------------------------------------------------


class CreateTaskArgs(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    horizon: Horizon = Field(default=Horizon.WEEK, description="week | term | year | someday")
    due_at: AwareDatetime | None = None


_HORIZON_LABEL = {
    Horizon.WEEK: "this week",
    Horizon.TERM: "this term",
    Horizon.YEAR: "this year",
    Horizon.SOMEDAY: "someday",
}


async def _create_task(args: CreateTaskArgs, deps: ToolDeps) -> str:
    task = Task(
        id=new_id(),
        title=args.title,
        horizon=args.horizon,
        due_at=args.due_at.astimezone(UTC) if args.due_at else None,
        created_at=deps.clock.now(),
    )
    await deps.repos.tasks.add(task)
    return f"Added '{task.title}' to {_HORIZON_LABEL[task.horizon]}."


def _describe_task(args: CreateTaskArgs, tz: ZoneInfo) -> tuple[str, str]:
    summary = _HORIZON_LABEL[args.horizon]
    if args.due_at:
        summary += f", due {fmt_local(args.due_at, tz)}"
    return f"Task: {args.title}", summary


# --- list_reminders (read-only) --------------------------------------------------------------


class ListRemindersArgs(BaseModel):
    pass


async def _list_reminders(_: ListRemindersArgs, deps: ToolDeps) -> str:
    upcoming = await deps.repos.reminders.find(ReminderStatus.SCHEDULED)
    if not upcoming:
        return "You have no upcoming reminders."
    return "Upcoming: " + "; ".join(f"{r.text} ({fmt_local(r.due_at, deps.tz)})" for r in upcoming)


# --- list_tasks (read-only) ------------------------------------------------------------------


class ListTasksArgs(BaseModel):
    horizon: Horizon | None = Field(default=None, description="Only this horizon; empty: all")


async def _list_tasks(args: ListTasksArgs, deps: ToolDeps) -> str:
    open_tasks = await deps.repos.tasks.find(args.horizon, done=False)
    where = f" for {_HORIZON_LABEL[args.horizon]}" if args.horizon else ""
    if not open_tasks:
        return f"You have no open tasks{where}."
    lines = []
    for horizon in Horizon:
        titles = [
            t.title + (f" (due {fmt_local(t.due_at, deps.tz)})" if t.due_at else "")
            for t in open_tasks
            if t.horizon == horizon
        ]
        if titles:
            lines.append(f"{_HORIZON_LABEL[horizon].capitalize()}: " + "; ".join(titles))
    count = len(open_tasks)
    return f"{count} open task{'s' if count != 1 else ''}{where}:\n" + "\n".join(lines)


# --- search_email (read-only) ----------------------------------------------------------------


class SearchEmailArgs(BaseModel):
    query: str = Field(
        default="",
        max_length=300,
        description="Gmail search, e.g. 'from:alice is:unread newer_than:7d'. Empty: the inbox.",
    )
    limit: int = Field(default=5, ge=1, le=20)


async def _search_email(args: SearchEmailArgs, deps: ToolDeps) -> str:
    found = await deps.mail.search(args.query or "in:inbox", args.limit)
    if not found:
        return "No emails match." if args.query else "Your inbox is empty."
    lines = [
        f"{'* ' if m.unread else ''}{m.sender}: {m.subject} ({fmt_local(m.received_at, deps.tz)})"
        + (f" - {m.snippet[:140]}" if m.snippet else "")
        for m in found
    ]
    return f"{len(found)} email{'s' if len(found) != 1 else ''}:\n" + "\n".join(lines)


# --- send_email (the card is the draft) ------------------------------------------------------

Address = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, max_length=254, pattern=r"^[^@\s<>,;]+@[^@\s<>,;]+\.[^@\s<>,;]+$"
    ),
]


class SendEmailArgs(BaseModel):
    to: list[Address] = Field(min_length=1, max_length=10, description="Recipient addresses")
    cc: list[Address] = Field(default_factory=list, max_length=10)
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20000, json_schema_extra={"format": "multiline"})


async def _send_email(args: SendEmailArgs, deps: ToolDeps) -> str:
    draft = EmailDraft(to=args.to, cc=args.cc, subject=args.subject, body=args.body)
    await deps.mail.send(draft)
    return f"Sent to {', '.join(args.to)}."


def _describe_email(args: SendEmailArgs, _tz: ZoneInfo) -> tuple[str, str]:
    return f"Email to {', '.join(args.to)}", args.subject


def _email_preview(args: SendEmailArgs) -> str:
    head = [f"To: {', '.join(args.to)}"]
    if args.cc:
        head.append(f"Cc: {', '.join(args.cc)}")
    head.append(f"Subject: {args.subject}")
    return "\n".join(head) + "\n\n" + args.body


# --- list_events (read-only) -----------------------------------------------------------------


class ListEventsArgs(_Period):
    pass


async def _list_events(args: ListEventsArgs, deps: ToolDeps) -> str:
    events = await deps.calendar.list_events(args.start, args.end)
    period = fmt_span(args.start, args.end, deps.tz)
    if not events:
        return f"Nothing on your calendar ({period})."
    lines = []
    for e in events:
        when = (
            f"{e.start.astimezone(deps.tz):%a %b %d}, all day"
            if is_all_day(e, deps.tz)
            else fmt_span(e.start, e.end, deps.tz)
        )
        lines.append(f"{when}: {e.title}" + (f" ({e.location})" if e.location else ""))
    return f"{len(events)} event{'s' if len(events) != 1 else ''}:\n" + "\n".join(lines)


# --- create_event (with a conflict check) ----------------------------------------------------


class CreateEventArgs(_Period):
    title: str = Field(min_length=1, max_length=300)
    location: str | None = Field(default=None, max_length=300)
    description: str | None = Field(
        default=None, max_length=5000, json_schema_extra={"format": "multiline"}
    )


async def _create_event(args: CreateEventArgs, deps: ToolDeps) -> str:
    event = CalendarEvent(
        title=args.title,
        start=args.start,
        end=args.end,
        location=args.location,
        description=args.description,
    )
    await deps.calendar.create_event(event)
    return f"Added to your calendar: {args.title}, {fmt_span(args.start, args.end, deps.tz)}."


def _describe_event(args: CreateEventArgs, tz: ZoneInfo) -> tuple[str, str]:
    summary = fmt_span(args.start, args.end, tz)
    if args.location:
        summary += f", {args.location}"
    return f"Event: {args.title}", summary


async def _event_conflicts(args: CreateEventArgs, deps: ToolDeps) -> list[str]:
    events = await deps.calendar.list_events(args.start, args.end)
    return [
        f"Overlaps {e.title}, {fmt_span(e.start, e.end, deps.tz)}"
        for e in conflicts(events, args.start, args.end, deps.tz)
    ]


# --- find_free_time (read-only) --------------------------------------------------------------


class FindFreeTimeArgs(_Period):
    duration_minutes: int = Field(default=60, ge=15, le=600, description="How long it needs")


MAX_SLOTS = 6


async def _find_free_time(args: FindFreeTimeArgs, deps: ToolDeps) -> str:
    start = max(args.start, deps.clock.now())  # never offer time that's already gone
    length = _fmt_minutes(args.duration_minutes)
    if start >= args.end:
        return "That time has already passed."
    events = await deps.calendar.list_events(start, args.end)
    slots = free_slots(events, start, args.end, args.duration_minutes, deps.tz, deps.day_hours)
    hours = f"{deps.day_hours[0]:02d}:00-{deps.day_hours[1]:02d}:00"
    if not slots:
        return f"No free {length} between {hours} in {fmt_span(start, args.end, deps.tz)}."
    shown = "\n".join(fmt_span(a, b, deps.tz) for a, b in slots[:MAX_SLOTS])
    more = f"\n(+{len(slots) - MAX_SLOTS} more)" if len(slots) > MAX_SLOTS else ""
    return f"Free for {length} ({hours}):\n{shown}{more}"


def _fmt_minutes(minutes: int) -> str:
    hours, rest = divmod(minutes, 60)
    if not hours:
        return f"{rest} min"
    return f"{hours} h" + (f" {rest} min" if rest else "")


def default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="create_reminder",
            description="Create a one-off or recurring reminder, pushed to the owner's phone.",
            args_model=CreateReminderArgs,
            read_only=False,
            describe=_describe_reminder,
            execute=_create_reminder,
        )
    )
    registry.register(
        Tool(
            name="create_task",
            description="Add a task to a horizon: this week, this term, this year or someday.",
            args_model=CreateTaskArgs,
            read_only=False,
            describe=_describe_task,
            execute=_create_task,
        )
    )
    registry.register(
        Tool(
            name="list_reminders",
            description="List the owner's upcoming reminders.",
            args_model=ListRemindersArgs,
            read_only=True,
            describe=lambda _args, _tz: ("List reminders", ""),
            execute=_list_reminders,
        )
    )
    registry.register(
        Tool(
            name="list_tasks",
            description="List the owner's open tasks, optionally for one horizon.",
            args_model=ListTasksArgs,
            read_only=True,
            describe=lambda args, _tz: ("List tasks", args.horizon or ""),
            execute=_list_tasks,
        )
    )
    registry.register(
        Tool(
            name="search_email",
            description="Search the owner's email (read-only; mail never leaves this machine).",
            args_model=SearchEmailArgs,
            read_only=True,
            describe=lambda args, _tz: ("Search email", args.query),
            execute=_search_email,
        )
    )
    registry.register(
        Tool(
            name="send_email",
            description="Draft an email. It is sent only when the owner approves the card.",
            args_model=SendEmailArgs,
            read_only=False,
            describe=_describe_email,
            execute=_send_email,
            risk=Risk.EXTERNAL,
            preview=_email_preview,
        )
    )
    registry.register(
        Tool(
            name="list_events",
            description="List the owner's calendar events in a period.",
            args_model=ListEventsArgs,
            read_only=True,
            describe=lambda args, tz: ("List events", fmt_span(args.start, args.end, tz)),
            execute=_list_events,
        )
    )
    registry.register(
        Tool(
            name="create_event",
            description="Add an event to the owner's calendar, warning about overlaps.",
            args_model=CreateEventArgs,
            read_only=False,
            describe=_describe_event,
            execute=_create_event,
            risk=Risk.EXTERNAL,
            check=_event_conflicts,
        )
    )
    registry.register(
        Tool(
            name="find_free_time",
            description="Find free slots of a given length in the owner's calendar.",
            args_model=FindFreeTimeArgs,
            read_only=True,
            describe=lambda args, tz: ("Find free time", fmt_span(args.start, args.end, tz)),
            execute=_find_free_time,
        )
    )
    return registry
