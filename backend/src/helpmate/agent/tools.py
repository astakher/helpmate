"""Typed tools the agent can call.

A tool is a pydantic args model plus an async `execute`. `read_only` tools run immediately;
every other tool goes through the policy engine and becomes a Proposal first.
Workstream A adds tools here (file_item, draft_email, …); B's connectors back some of them.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, Field

from helpmate.domain.models import Horizon, Reminder, ReminderStatus, Risk, Task, ToolSpec, new_id
from helpmate.domain.ports import Clock, Repositories, SchedulerPort


@dataclass(frozen=True)
class ToolDeps:
    repos: Repositories
    scheduler: SchedulerPort
    clock: Clock
    tz: ZoneInfo


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
    return registry
