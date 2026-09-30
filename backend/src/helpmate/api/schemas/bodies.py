from __future__ import annotations

from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from helpmate.domain.models import (
    AuditEntry,
    ChatMessage,
    ChatSession,
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


class TodayOut(Body):
    date: str  # local date, YYYY-MM-DD
    timezone: str
    reminders: list[Reminder]
    tasks: list[Task]
    pending_proposals: list[Proposal]


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
