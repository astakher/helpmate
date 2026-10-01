"""Domain models shared by every workstream.

HelpMate is single-user: everything belongs to the owner. All datetimes are timezone-aware
and stored in UTC; conversion to the owner's timezone happens at the edges.
"""

from __future__ import annotations

import uuid
from datetime import time
from enum import StrEnum
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

OWNER_ID = "owner"

Source = Literal["text", "voice"]


def new_id() -> str:
    return uuid.uuid4().hex


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Users -----------------------------------------------------------------------------------


class User(DomainModel):
    id: str
    display_name: str
    mfa_enabled: bool = False


class LoginResult(DomainModel):
    """No token and no MFA step = wrong username or password (401). `retry_after_seconds` = too
    many failures, locked out for that long (429). Both added Sep 30, additive."""

    mfa_required: bool
    challenge_id: str | None = None  # pass back with the TOTP code
    session_token: str | None = None  # set when no MFA step is needed; goes in a cookie, never JSON
    retry_after_seconds: int | None = None


# --- Proposals (the approval cards) ----------------------------------------------------------


class Risk(StrEnum):
    WRITE = "write"  # changes the owner's own data
    EXTERNAL = "external"  # leaves the machine (email, calendar)


class ProposalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    FAILED = "failed"


class Proposal(DomainModel):
    """A write the agent wants to make. Nothing runs until the owner approves it."""

    id: str
    session_id: str | None = None
    tool: str
    title: str
    summary: str
    args: dict[str, Any]
    preview: str | None = None  # e.g. the full email body
    # Things the owner should know before approving, e.g. "Overlaps Standup, 09:00-09:30".
    # Added Sep 30, additive.
    warnings: list[str] = Field(default_factory=list)
    risk: Risk = Risk.WRITE
    status: ProposalStatus = ProposalStatus.PENDING
    created_at: AwareDatetime
    decided_at: AwareDatetime | None = None
    result: str | None = None


# --- Reminders and tasks ---------------------------------------------------------------------


class ReminderStatus(StrEnum):
    SCHEDULED = "scheduled"
    SENT = "sent"
    CANCELLED = "cancelled"


class Reminder(DomainModel):
    id: str
    text: str
    due_at: AwareDatetime
    recurrence: str | None = None  # RFC 5545 RRULE, e.g. "FREQ=WEEKLY;BYDAY=MO"
    status: ReminderStatus = ReminderStatus.SCHEDULED
    created_at: AwareDatetime
    sent_at: AwareDatetime | None = None


class Horizon(StrEnum):
    WEEK = "week"
    TERM = "term"
    YEAR = "year"
    SOMEDAY = "someday"


class Task(DomainModel):
    id: str
    title: str
    horizon: Horizon = Horizon.WEEK
    folder_id: str | None = None
    due_at: AwareDatetime | None = None
    done: bool = False
    created_at: AwareDatetime


# --- Folders and items (PARA + user-defined folders with custom fields) ----------------------


class FolderKind(StrEnum):
    PARA = "para"
    CUSTOM = "custom"


class FieldType(StrEnum):
    TEXT = "text"
    NUMBER = "number"
    DATE = "date"
    SELECT = "select"
    RATING = "rating"
    BOOL = "bool"


class FieldDef(DomainModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")
    label: str
    type: FieldType = FieldType.TEXT
    options: list[str] | None = None  # for SELECT


class Folder(DomainModel):
    id: str
    name: str
    kind: FolderKind = FolderKind.CUSTOM
    fields: list[FieldDef] = []
    created_at: AwareDatetime


class Item(DomainModel):
    id: str
    folder_id: str
    title: str
    fields: dict[str, Any] = {}
    source: str | None = None  # where it came from, e.g. "chat:<session_id>"
    created_at: AwareDatetime


# --- Memory ----------------------------------------------------------------------------------


class SuggestionStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class MemorySuggestion(DomainModel):
    """A fact the agent noticed. Stored as a MemoryFact only if the owner approves it."""

    id: str
    text: str
    source: str
    status: SuggestionStatus = SuggestionStatus.PENDING
    created_at: AwareDatetime


class MemoryFact(DomainModel):
    id: str
    text: str
    source: str
    created_at: AwareDatetime


# --- Chat ------------------------------------------------------------------------------------


class Role(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class ChatSession(DomainModel):
    id: str
    title: str | None = None  # set from the first message unless given
    created_at: AwareDatetime
    last_message_at: AwareDatetime | None = None  # chat list order. Added Oct 1, additive.


class ChatMessage(DomainModel):
    id: str
    session_id: str
    role: Role
    text: str
    source: Source = "text"
    created_at: AwareDatetime


# --- Documents (the file vault; added Oct 1) -------------------------------------------------


class Document(DomainModel):
    """An uploaded file. The bytes live in the file store under `storage_key`; its text, cut
    into passages with embeddings, in the document repository."""

    id: str
    name: str
    content_type: str
    size: int  # bytes
    pages: int | None = None  # PDFs
    passages: int = 0
    note: str | None = None  # e.g. "only the first 400 passages were indexed"
    storage_key: str
    created_at: AwareDatetime


class DocumentPassage(DomainModel):
    id: str
    document_id: str
    document_name: str
    page: int | None = None  # 1-based, PDFs only
    index: int  # position in the document
    text: str


# --- Notifications ---------------------------------------------------------------------------


class NotificationKind(StrEnum):
    REMINDER = "reminder"
    BRIEF = "brief"
    SYSTEM = "system"
    TEST = "test"


class Notification(DomainModel):
    id: str
    kind: NotificationKind
    title: str
    body: str
    url: str = "/"
    tag: str | None = None  # same tag replaces an earlier notification on the device
    urgent: bool = False  # urgent ones ignore quiet hours (e.g. reminders the owner set)
    due_at: AwareDatetime | None = None  # for latency measurement


class DeliveryResult(DomainModel):
    notification_id: str
    delivered: int  # number of devices the push service accepted it for
    deferred: bool = False  # held back by quiet hours / rate limit
    detail: str | None = None
    # devices the push service refused or couldn't be reached for (not expired ones, which are
    # removed): the scheduler retries when this is > 0 and nothing was delivered. Oct 1, additive.
    failed: int = 0


class Delivery(DomainModel):
    """Delivery record used to measure the 'reminder reaches the phone within 60 s' target."""

    notification_id: str
    kind: NotificationKind
    due_at: AwareDatetime | None = None
    sent_at: AwareDatetime
    received_at: AwareDatetime | None = None  # set by the service worker's ack


class PushKeys(DomainModel):
    p256dh: str
    auth: str


class PushSubscription(DomainModel):
    endpoint: str
    keys: PushKeys
    user_agent: str | None = None
    created_at: AwareDatetime


class QuietHours(DomainModel):
    start: time  # local time, e.g. 22:00
    end: time  # local time, e.g. 07:00 (may wrap past midnight)


class NotificationSettings(DomainModel):
    quiet_hours: QuietHours | None = None
    timezone: str = "America/Toronto"
    max_per_hour: int = Field(default=6, ge=1, le=60)
    private_previews: bool = (
        False  # send generic text so no personal content transits the push service
    )
    # Evening check-in: a daily push at this local time summing up the week and tomorrow; None =
    # off. Added Oct 1, additive.
    checkin_at: time | None = None


# --- Audit -----------------------------------------------------------------------------------


class Actor(StrEnum):
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"


class AuditEntry(DomainModel):
    id: str
    at: AwareDatetime
    actor: Actor
    action: str  # e.g. "proposal.created", "proposal.approved", "tool.executed"
    target: str | None = None
    detail: dict[str, Any] = {}


# --- Voice -----------------------------------------------------------------------------------


class Transcript(DomainModel):
    text: str
    language: str | None = None
    duration_ms: int  # length of the audio
    stt_ms: int  # time spent transcribing


# --- LLM -------------------------------------------------------------------------------------


class ToolCall(DomainModel):
    id: str
    name: str
    arguments: dict[str, Any]


class ToolSpec(DomainModel):
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema of the arguments


class LLMMessage(DomainModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_calls: list[ToolCall] | None = None
    tool_name: str | None = None  # for role="tool"


class LLMChunk(DomainModel):
    text: str = ""
    tool_calls: list[ToolCall] = []
    done: bool = False
    prompt_tokens: int | None = None
    output_tokens: int | None = None


# --- Mail and calendar (Workstream B, proposed v0.1 — B to refine) ---------------------------


class EmailDraft(DomainModel):
    to: list[str]
    subject: str
    body: str
    cc: list[str] = []
    in_reply_to: str | None = None  # the replied-to message's Message-ID header
    thread_id: str | None = None  # the provider's thread, so a reply lands in it. Oct 1, additive.


class EmailSummary(DomainModel):
    id: str
    sender: str
    subject: str
    snippet: str
    received_at: AwareDatetime
    unread: bool = True
    # the provider's labels, e.g. Gmail's CATEGORY_PROMOTIONS (inbox triage). Oct 1, additive.
    labels: list[str] = []


class EmailDetail(DomainModel):
    """One message, read in full, for drafting a reply. Its text is untrusted (inbox triage)."""

    id: str
    thread_id: str | None = None
    sender: str  # the From header, e.g. "Sam Lee <sam@example.com>"
    subject: str
    body: str  # plain text, truncated
    message_id: str | None = None  # the RFC 5322 Message-ID header, for In-Reply-To
    received_at: AwareDatetime
    labels: list[str] = []


class CalendarEvent(DomainModel):
    id: str | None = None
    title: str
    start: AwareDatetime
    end: AwareDatetime
    location: str | None = None
    description: str | None = None
