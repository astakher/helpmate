from __future__ import annotations

from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from helpmate.domain.models import (
    AuditEntry,
    CalendarEvent,
    ChatMessage,
    ChatSession,
    EmailSummary,
    FieldDef,
    Folder,
    Horizon,
    Item,
    MemoryFact,
    MemorySuggestion,
    Proposal,
    PushKeys,
    Reminder,
    Risk,
    Source,
    Task,
)


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- health ---


class AdapterInfo(Body):
    name: str
    fake: bool


class HealthOut(Body):
    status: Literal["ok"] = "ok"
    version: str
    adapters: dict[str, AdapterInfo]


# --- tools ---


class ToolInfo(Body):
    name: str
    description: str
    read_only: bool
    risk: Risk
    parameters: dict[str, Any]  # JSON Schema of the arguments; the Edit form is built from it


# --- auth ---


class LoginIn(Body):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class LoginOut(Body):
    mfa_required: bool
    challenge_id: str | None = None


class MfaIn(Body):
    challenge_id: str
    code: str = Field(pattern=r"^\d{6}$")


class MfaEnrollOut(Body):
    otpauth_uri: str


class MfaConfirmIn(Body):
    """POST /api/auth/mfa/enroll/confirm (added Sep 30, additive): the first code from the app."""

    code: str = Field(pattern=r"^\d{6}$")


# --- chat ---


class CreateSessionIn(Body):
    title: str | None = Field(default=None, max_length=200)


class PostMessageIn(Body):
    text: str = Field(min_length=1, max_length=4000)
    source: Source = "text"


# --- proposals ---


class DecisionIn(Body):
    decision: Literal["approve", "reject", "edit"]
    args: dict[str, Any] | None = None  # required for "edit"


# --- organize ---


class CreateFolderIn(Body):
    name: str = Field(min_length=1, max_length=100)
    fields: list[FieldDef] = []


class CreateItemIn(Body):
    title: str = Field(min_length=1, max_length=300)
    fields: dict[str, Any] = {}


class CreateTaskIn(Body):
    title: str = Field(min_length=1, max_length=300)
    horizon: Horizon = Horizon.WEEK
    folder_id: str | None = None
    due_at: AwareDatetime | None = None


class PatchTaskIn(Body):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    horizon: Horizon | None = None
    done: bool | None = None
    due_at: AwareDatetime | None = None


class TimeRange(Body):
    start: AwareDatetime
    end: AwareDatetime


class TodayOut(Body):
    date: str  # local date, YYYY-MM-DD
    timezone: str
    reminders: list[Reminder]
    tasks: list[Task]
    pending_proposals: list[Proposal]
    # The daily brief (added Oct 1, additive). A section that couldn't be read (e.g. Google's
    # sign-in expired) is empty and says why in its *_error, so the rest of the brief still loads.
    events: list[CalendarEvent] = []  # today's, all-day ones included
    free_slots: list[TimeRange] = []  # from now to the end of the owner's day, >= 30 min
    unread: list[EmailSummary] = []  # newest unread in the inbox, at most 5
    calendar_error: str | None = None
    mail_error: str | None = None


# --- week plan (added Oct 1) ---


class DayPlan(Body):
    date: str  # local date, YYYY-MM-DD
    events: list[CalendarEvent]
    free_slots: list[TimeRange]  # inside the owner's day hours, >= 30 min (today: from now)
    reminders: list[Reminder]  # scheduled ones due that day
    tasks_due: list[Task]  # open tasks with a due date that day


class WeekOut(Body):
    """The next 7 days, starting today, plus this week's tasks that have no date yet."""

    timezone: str
    days: list[DayPlan]
    unscheduled: list[Task]
    calendar_error: str | None = None


class ScheduleTaskIn(Body):
    task_id: str
    minutes: int = Field(default=60, ge=15, le=480)


# --- inbox triage (added Oct 1) ---


class TriagedEmail(Body):
    email: EmailSummary
    category: Literal["reply", "fyi", "low"]
    reason: str  # the model's or a rule's, with links and addresses removed
    suspicious: bool  # has text that looks aimed at an AI; HelpMate ignored it
    sorted_by: Literal["rules", "model"]


class InboxOut(Body):
    items: list[TriagedEmail]
    error: str | None = None  # the mailbox couldn't be read (e.g. Google signed out)


# --- memory ---


class SuggestionDecisionIn(Body):
    decision: Literal["approve", "reject"]


class FactUpdateIn(Body):
    """PATCH /api/memory/facts/{id} (added Sep 30, additive): the owner corrects a fact."""

    text: str = Field(min_length=1, max_length=500)


class ExportOut(Body):
    exported_at: AwareDatetime
    folders: list[Folder]
    items: list[Item]
    tasks: list[Task]
    reminders: list[Reminder]
    facts: list[MemoryFact]
    suggestions: list[MemorySuggestion]
    proposals: list[Proposal]
    chat_sessions: list[ChatSession]
    chat_messages: list[ChatMessage]
    audit: list[AuditEntry]


# --- voice ---


class SpeakIn(Body):
    text: str = Field(min_length=1, max_length=2000)
    voice: str | None = None


# --- push ---


class VapidKeyOut(Body):
    public_key: str | None  # None until VAPID keys are configured


class SubscriptionIn(Body):
    endpoint: str = Field(min_length=10, max_length=2000)
    keys: PushKeys
    user_agent: str | None = Field(default=None, max_length=500)


class UnsubscribeIn(Body):
    endpoint: str


class AckIn(Body):
    notification_id: str
    received_at: AwareDatetime
