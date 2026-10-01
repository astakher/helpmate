"""Ports: the interfaces every adapter implements.

This file is the plug-in contract between workstreams. The API layer and the agent depend only
on these Protocols; `container.py` picks a concrete adapter for each one from settings.
Every port has a fake (adapters/fakes/) so the whole system runs before the real adapter exists.

Owner of the real adapter is noted on each port.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol

from helpmate.domain.events import ChatEvent
from helpmate.domain.models import (
    AuditEntry,
    CalendarEvent,
    ChatMessage,
    ChatSession,
    Delivery,
    DeliveryResult,
    EmailDraft,
    EmailSummary,
    Folder,
    Horizon,
    Item,
    LLMChunk,
    LLMMessage,
    LoginResult,
    MemoryFact,
    MemorySuggestion,
    Notification,
    NotificationSettings,
    Proposal,
    ProposalStatus,
    PushSubscription,
    Reminder,
    ReminderStatus,
    Source,
    SuggestionStatus,
    Task,
    ToolSpec,
    Transcript,
    User,
)


class Adapter(Protocol):
    """Every adapter reports what it is, for GET /api/health and the System status page."""

    name: str  # e.g. "fake", "ollama:llama3.2:3b", "webpush"
    is_fake: bool


class Clock(Protocol):
    def now(self) -> datetime:
        """Current time, timezone-aware UTC. Tests use a FakeClock to move time."""
        ...


# --- Inference (Workstream A) ----------------------------------------------------------------


class AgentPort(Adapter, Protocol):
    """Turns one user message into a stream of ChatEvents. Real impl: agent loop (A)."""

    def run(self, session_id: str, text: str, source: Source) -> AsyncIterator[ChatEvent]: ...


class LLMPort(Adapter, Protocol):
    """Chat completion with optional tool calling, streamed. Real impl: Ollama (A).

    `json_schema` (added Sep 29, additive): constrain the reply to JSON matching this schema
    (structured output), e.g. the agent loop's routing step."""

    def chat(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[ToolSpec] = (),
        json_schema: Mapping[str, Any] | None = None,
    ) -> AsyncIterator[LLMChunk]: ...


class EmbeddingPort(Adapter, Protocol):
    """Text embeddings for hybrid search. Real impl: Ollama embeddings (A)."""

    dimensions: int

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


# --- Voice (Workstream C) --------------------------------------------------------------------


class STTPort(Adapter, Protocol):
    """Speech-to-text. Audio is processed in memory and never stored. Real impl: speech service."""

    async def transcribe(
        self, audio: bytes, mime: str, language: str | None = None
    ) -> Transcript: ...


class TTSPort(Adapter, Protocol):
    """Text-to-speech, returns WAV bytes. Real impl: speech service (Kokoro)."""

    async def speak(self, text: str, voice: str | None = None) -> bytes: ...


# --- Notifications (Workstream C) and scheduling (Workstream B) ------------------------------


class NotifierPort(Adapter, Protocol):
    """Delivers a notification to all of the owner's devices. Real impl: Web Push (C).

    The scheduler only ever calls this; it never knows about Web Push.
    """

    async def notify(self, notification: Notification) -> DeliveryResult: ...


class SchedulerPort(Adapter, Protocol):
    """Fires reminders (and later briefs, outbox sends) at the right time. Real impl: Postgres
    job queue (B)."""

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def schedule(self, reminder: Reminder) -> None: ...

    async def cancel(self, reminder_id: str) -> None: ...


# --- Auth (Workstream B) ---------------------------------------------------------------------


class AuthPort(Adapter, Protocol):
    """Password + TOTP login and session validation. Real impl: B (HELPMATE_AUTH=totp)."""

    async def user_for(self, session_token: str | None) -> User | None: ...

    async def login(self, username: str, password: str) -> LoginResult: ...

    async def verify_mfa(self, challenge_id: str, code: str) -> str | None:
        """Returns a session token, or None if the code is wrong."""
        ...

    async def enroll_mfa(self) -> str:
        """Returns an otpauth:// URI for the authenticator-app QR code."""
        ...

    async def confirm_mfa(self, code: str) -> bool:
        """Finish enrolment (added Sep 30, additive): True if `code` matches the secret from
        enroll_mfa, and from then on login asks for a code (User.mfa_enabled)."""
        ...

    async def logout(self, session_token: str | None) -> None: ...


# --- Connectors (Workstream B, proposed v0.1) ------------------------------------------------


class MailPort(Adapter, Protocol):
    async def search(self, query: str, limit: int = 20) -> list[EmailSummary]: ...

    async def send(self, draft: EmailDraft) -> str: ...


class CalendarPort(Adapter, Protocol):
    async def list_events(self, start: datetime, end: datetime) -> list[CalendarEvent]: ...

    async def create_event(self, event: CalendarEvent) -> CalendarEvent: ...


# --- Repositories (Workstream B: Postgres + pgvector) ----------------------------------------
# All methods are async so the in-memory fakes and the Postgres adapters are interchangeable.


class ProposalRepo(Protocol):
    async def add(self, proposal: Proposal) -> None: ...
    async def get(self, proposal_id: str) -> Proposal | None: ...
    async def find(self, status: ProposalStatus | None = None) -> list[Proposal]: ...
    async def update(self, proposal: Proposal) -> None: ...


class ReminderRepo(Protocol):
    async def add(self, reminder: Reminder) -> None: ...
    async def get(self, reminder_id: str) -> Reminder | None: ...
    async def find(self, status: ReminderStatus | None = None) -> list[Reminder]: ...
    async def due(self, now: datetime) -> list[Reminder]: ...
    async def update(self, reminder: Reminder) -> None: ...


class TaskRepo(Protocol):
    async def add(self, task: Task) -> None: ...
    async def get(self, task_id: str) -> Task | None: ...
    async def find(
        self, horizon: Horizon | None = None, done: bool | None = None
    ) -> list[Task]: ...
    async def update(self, task: Task) -> None: ...


class FolderRepo(Protocol):
    async def add(self, folder: Folder) -> None: ...
    async def get(self, folder_id: str) -> Folder | None: ...
    async def find(self) -> list[Folder]: ...
    async def add_item(self, item: Item) -> None: ...
    async def find_items(self, folder_id: str) -> list[Item]: ...


class ChatRepo(Protocol):
    async def add_session(self, session: ChatSession) -> None: ...
    async def get_session(self, session_id: str) -> ChatSession | None: ...
    async def find_sessions(self) -> list[ChatSession]: ...  # most recent activity first
    async def update_session(self, session: ChatSession) -> None: ...  # added Oct 1
    async def delete_session(self, session_id: str) -> bool: ...  # with its messages; Oct 1
    async def add_message(self, message: ChatMessage) -> None: ...
    async def find_messages(self, session_id: str) -> list[ChatMessage]: ...


class MemoryRepo(Protocol):
    async def add_suggestion(self, suggestion: MemorySuggestion) -> None: ...
    async def get_suggestion(self, suggestion_id: str) -> MemorySuggestion | None: ...
    async def find_suggestions(
        self, status: SuggestionStatus | None = None
    ) -> list[MemorySuggestion]: ...
    async def update_suggestion(self, suggestion: MemorySuggestion) -> None: ...
    async def add_fact(self, fact: MemoryFact) -> None: ...
    async def find_facts(self) -> list[MemoryFact]: ...
    async def update_fact(self, fact: MemoryFact) -> bool:
        """Replace a stored fact (the owner edited it). False if it doesn't exist. Added Sep 30."""
        ...

    async def delete_fact(self, fact_id: str) -> bool: ...


class PushSubscriptionRepo(Protocol):
    async def upsert(self, subscription: PushSubscription) -> None: ...
    async def remove(self, endpoint: str) -> bool: ...
    async def find(self) -> list[PushSubscription]: ...


class DeliveryRepo(Protocol):
    async def record(self, delivery: Delivery) -> None: ...
    async def ack(self, notification_id: str, received_at: datetime) -> bool: ...
    async def find(self) -> list[Delivery]: ...


class AuditRepo(Protocol):
    async def add(self, entry: AuditEntry) -> None: ...
    async def find(self, limit: int = 100) -> list[AuditEntry]: ...


class SettingsRepo(Protocol):
    async def get_notification_settings(self) -> NotificationSettings: ...
    async def put_notification_settings(self, settings: NotificationSettings) -> None: ...


class Repositories(Adapter, Protocol):
    """One bundle so the whole persistence layer swaps with HELPMATE_REPO."""

    proposals: ProposalRepo
    reminders: ReminderRepo
    tasks: TaskRepo
    folders: FolderRepo
    chat: ChatRepo
    memory: MemoryRepo
    push_subscriptions: PushSubscriptionRepo
    deliveries: DeliveryRepo
    audit: AuditRepo
    settings: SettingsRepo
