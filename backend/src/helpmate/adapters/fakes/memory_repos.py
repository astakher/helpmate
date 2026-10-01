"""In-memory repositories (HELPMATE_REPO=memory).

Models are copied on the way in and out, so callers can't mutate stored state by accident. That
matches how the Postgres adapters will behave and keeps the fake honest.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from helpmate.domain.models import (
    AuditEntry,
    ChatMessage,
    ChatSession,
    Delivery,
    FieldDef,
    FieldType,
    Folder,
    FolderKind,
    Horizon,
    Item,
    MemoryFact,
    MemorySuggestion,
    NotificationSettings,
    Proposal,
    ProposalStatus,
    PushSubscription,
    Reminder,
    ReminderStatus,
    SuggestionStatus,
    Task,
    new_id,
)


def _copy[M: BaseModel](model: M) -> M:
    return model.model_copy(deep=True)


class _Store[M: BaseModel]:
    def __init__(self) -> None:
        self._rows: dict[str, M] = {}

    def put(self, key: str, model: M) -> None:
        self._rows[key] = _copy(model)

    def get(self, key: str) -> M | None:
        row = self._rows.get(key)
        return _copy(row) if row is not None else None

    def pop(self, key: str) -> bool:
        return self._rows.pop(key, None) is not None

    def values(self) -> list[M]:
        return [_copy(m) for m in self._rows.values()]


class InMemoryProposalRepo:
    def __init__(self) -> None:
        self._s: _Store[Proposal] = _Store()

    async def add(self, proposal: Proposal) -> None:
        self._s.put(proposal.id, proposal)

    async def get(self, proposal_id: str) -> Proposal | None:
        return self._s.get(proposal_id)

    async def find(self, status: ProposalStatus | None = None) -> list[Proposal]:
        rows = [p for p in self._s.values() if status is None or p.status == status]
        return sorted(rows, key=lambda p: p.created_at, reverse=True)

    async def update(self, proposal: Proposal) -> None:
        self._s.put(proposal.id, proposal)


class InMemoryReminderRepo:
    def __init__(self) -> None:
        self._s: _Store[Reminder] = _Store()

    async def add(self, reminder: Reminder) -> None:
        self._s.put(reminder.id, reminder)

    async def get(self, reminder_id: str) -> Reminder | None:
        return self._s.get(reminder_id)

    async def find(self, status: ReminderStatus | None = None) -> list[Reminder]:
        rows = [r for r in self._s.values() if status is None or r.status == status]
        return sorted(rows, key=lambda r: r.due_at)

    async def due(self, now: datetime) -> list[Reminder]:
        return [r for r in await self.find(ReminderStatus.SCHEDULED) if r.due_at <= now]

    async def update(self, reminder: Reminder) -> None:
        self._s.put(reminder.id, reminder)


class InMemoryTaskRepo:
    def __init__(self) -> None:
        self._s: _Store[Task] = _Store()

    async def add(self, task: Task) -> None:
        self._s.put(task.id, task)

    async def get(self, task_id: str) -> Task | None:
        return self._s.get(task_id)

    async def find(self, horizon: Horizon | None = None, done: bool | None = None) -> list[Task]:
        rows = [
            t
            for t in self._s.values()
            if (horizon is None or t.horizon == horizon) and (done is None or t.done == done)
        ]
        return sorted(rows, key=lambda t: t.created_at)

    async def update(self, task: Task) -> None:
        self._s.put(task.id, task)


class InMemoryFolderRepo:
    def __init__(self) -> None:
        self._folders: _Store[Folder] = _Store()
        self._items: _Store[Item] = _Store()

    async def add(self, folder: Folder) -> None:
        self._folders.put(folder.id, folder)

    async def get(self, folder_id: str) -> Folder | None:
        return self._folders.get(folder_id)

    async def find(self) -> list[Folder]:
        return sorted(self._folders.values(), key=lambda f: f.created_at)

    async def add_item(self, item: Item) -> None:
        self._items.put(item.id, item)

    async def find_items(self, folder_id: str) -> list[Item]:
        rows = [i for i in self._items.values() if i.folder_id == folder_id]
        return sorted(rows, key=lambda i: i.created_at)


class InMemoryChatRepo:
    def __init__(self) -> None:
        self._sessions: _Store[ChatSession] = _Store()
        self._messages: _Store[ChatMessage] = _Store()

    async def add_session(self, session: ChatSession) -> None:
        self._sessions.put(session.id, session)

    async def get_session(self, session_id: str) -> ChatSession | None:
        return self._sessions.get(session_id)

    async def find_sessions(self) -> list[ChatSession]:
        return sorted(
            self._sessions.values(),
            key=lambda s: s.last_message_at or s.created_at,
            reverse=True,
        )

    async def update_session(self, session: ChatSession) -> None:
        self._sessions.put(session.id, session)

    async def delete_session(self, session_id: str) -> bool:
        for message in self._messages.values():
            if message.session_id == session_id:
                self._messages.pop(message.id)
        return self._sessions.pop(session_id)

    async def add_message(self, message: ChatMessage) -> None:
        self._messages.put(message.id, message)

    async def find_messages(self, session_id: str) -> list[ChatMessage]:
        rows = [m for m in self._messages.values() if m.session_id == session_id]
        return sorted(rows, key=lambda m: m.created_at)


class InMemoryMemoryRepo:
    def __init__(self) -> None:
        self._suggestions: _Store[MemorySuggestion] = _Store()
        self._facts: _Store[MemoryFact] = _Store()

    async def add_suggestion(self, suggestion: MemorySuggestion) -> None:
        self._suggestions.put(suggestion.id, suggestion)

    async def get_suggestion(self, suggestion_id: str) -> MemorySuggestion | None:
        return self._suggestions.get(suggestion_id)

    async def find_suggestions(
        self, status: SuggestionStatus | None = None
    ) -> list[MemorySuggestion]:
        rows = [s for s in self._suggestions.values() if status is None or s.status == status]
        return sorted(rows, key=lambda s: s.created_at, reverse=True)

    async def update_suggestion(self, suggestion: MemorySuggestion) -> None:
        self._suggestions.put(suggestion.id, suggestion)

    async def add_fact(self, fact: MemoryFact) -> None:
        self._facts.put(fact.id, fact)

    async def find_facts(self) -> list[MemoryFact]:
        return sorted(self._facts.values(), key=lambda f: f.created_at, reverse=True)

    async def update_fact(self, fact: MemoryFact) -> bool:
        if self._facts.get(fact.id) is None:
            return False
        self._facts.put(fact.id, fact)
        return True

    async def delete_fact(self, fact_id: str) -> bool:
        return self._facts.pop(fact_id)


class InMemoryPushSubscriptionRepo:
    def __init__(self) -> None:
        self._s: _Store[PushSubscription] = _Store()

    async def upsert(self, subscription: PushSubscription) -> None:
        self._s.put(subscription.endpoint, subscription)

    async def remove(self, endpoint: str) -> bool:
        return self._s.pop(endpoint)

    async def find(self) -> list[PushSubscription]:
        return self._s.values()


class InMemoryDeliveryRepo:
    def __init__(self) -> None:
        self._s: _Store[Delivery] = _Store()

    async def record(self, delivery: Delivery) -> None:
        self._s.put(delivery.notification_id, delivery)

    async def ack(self, notification_id: str, received_at: datetime) -> bool:
        delivery = self._s.get(notification_id)
        if delivery is None:
            return False
        delivery.received_at = received_at
        self._s.put(notification_id, delivery)
        return True

    async def find(self) -> list[Delivery]:
        return sorted(self._s.values(), key=lambda d: d.sent_at)


class InMemoryAuditRepo:
    def __init__(self) -> None:
        self._rows: list[AuditEntry] = []

    async def add(self, entry: AuditEntry) -> None:
        self._rows.append(_copy(entry))

    async def find(self, limit: int = 100) -> list[AuditEntry]:
        return [_copy(e) for e in reversed(self._rows[-limit:])]


class InMemorySettingsRepo:
    def __init__(self) -> None:
        self._notifications = NotificationSettings()

    async def get_notification_settings(self) -> NotificationSettings:
        return _copy(self._notifications)

    async def put_notification_settings(self, settings: NotificationSettings) -> None:
        self._notifications = _copy(settings)


class InMemoryRepositories:
    name = "memory"
    is_fake = True

    def __init__(self) -> None:
        self.proposals = InMemoryProposalRepo()
        self.reminders = InMemoryReminderRepo()
        self.tasks = InMemoryTaskRepo()
        self.folders = InMemoryFolderRepo()
        self.chat = InMemoryChatRepo()
        self.memory = InMemoryMemoryRepo()
        self.push_subscriptions = InMemoryPushSubscriptionRepo()
        self.deliveries = InMemoryDeliveryRepo()
        self.audit = InMemoryAuditRepo()
        self.settings = InMemorySettingsRepo()

    async def seed(self, now: datetime, timezone: str) -> None:
        """Default PARA folders plus one example custom folder, so the UI has something to show."""
        for name in ("Projects", "Areas", "Resources", "Archive"):
            await self.folders.add(
                Folder(id=new_id(), name=name, kind=FolderKind.PARA, created_at=now)
            )
        await self.folders.add(
            Folder(
                id=new_id(),
                name="Books",
                kind=FolderKind.CUSTOM,
                created_at=now,
                fields=[
                    FieldDef(key="author", label="Author"),
                    FieldDef(
                        key="status",
                        label="Status",
                        type=FieldType.SELECT,
                        options=["to read", "reading", "done"],
                    ),
                    FieldDef(key="rating", label="Rating", type=FieldType.RATING),
                ],
            )
        )
        await self.settings.put_notification_settings(NotificationSettings(timezone=timezone))
