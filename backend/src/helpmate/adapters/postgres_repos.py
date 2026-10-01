# Stand-in for Workstream B - not part of the Part C deliverable
"""Postgres repositories (HELPMATE_REPO=postgres): the in-memory fakes' behaviour, made durable.

Each table keeps the full domain model as JSONB plus typed columns for what the repositories
filter and sort on (migrations/versions/0001_initial.py). Orderings and tie-breaks (`seq`) match
adapters/fakes/memory_repos.py, and both run the same suite: tests/contracts/test_repositories.py
(set HELPMATE_TEST_DATABASE_URL to include Postgres).

On start-up the container runs the Alembic migrations and, on an empty database, the same seed as
the in-memory repos (PARA folders + an example Books folder).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import asyncpg
from pydantic import BaseModel

from helpmate.adapters.fakes.memory_repos import InMemoryRepositories
from helpmate.domain.models import (
    AuditEntry,
    ChatMessage,
    ChatSession,
    Delivery,
    Folder,
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
)

BACKEND_DIR = Path(__file__).resolve().parents[3]  # adapters -> helpmate -> src -> backend


class Database:
    """One lazily created asyncpg pool shared by all repositories."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: asyncpg.Pool | None = None
        self._lock = asyncio.Lock()

    async def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            async with self._lock:
                if self._pool is None:
                    self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=5)
        return self._pool

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None


class _Table[M: BaseModel]:
    """Upsert / get / select / delete for one table of `model` rows."""

    def __init__(
        self,
        db: Database,
        name: str,
        model: type[M],
        key: tuple[str, Callable[[M], Any]],
        columns: dict[str, Callable[[M], Any]] | None = None,
    ) -> None:
        self._db, self._name, self._model = db, name, model
        self._key_column, self._key = key
        self._columns = columns or {}
        cols = [self._key_column, *self._columns, "data"]
        marks = ", ".join(f"${i}" for i in range(1, len(cols) + 1))
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols[1:])
        self._upsert = (
            f"INSERT INTO {name} ({', '.join(cols)}) VALUES ({marks}) "
            f"ON CONFLICT ({self._key_column}) DO UPDATE SET {updates}"
        )

    async def put(self, row: M) -> None:
        values = [self._key(row), *(get(row) for get in self._columns.values())]
        await (await self._db.pool()).execute(self._upsert, *values, row.model_dump_json())

    async def get(self, key: str) -> M | None:
        data = await (await self._db.pool()).fetchval(
            f"SELECT data FROM {self._name} WHERE {self._key_column} = $1", key
        )
        return self._model.model_validate_json(data) if data is not None else None

    async def select(
        self, where: str = "", params: Sequence[Any] = (), order: str = "seq"
    ) -> list[M]:
        sql = f"SELECT data FROM {self._name}"
        if where:
            sql += f" WHERE {where}"
        sql += f" ORDER BY {order}"
        rows = await (await self._db.pool()).fetch(sql, *params)
        return [self._model.model_validate_json(r["data"]) for r in rows]

    async def delete(self, key: str) -> bool:
        status = await (await self._db.pool()).execute(
            f"DELETE FROM {self._name} WHERE {self._key_column} = $1", key
        )
        return status.endswith(" 1")

    async def exists(self, key: str) -> bool:
        return bool(
            await (await self._db.pool()).fetchval(
                f"SELECT 1 FROM {self._name} WHERE {self._key_column} = $1", key
            )
        )


def _filters(**conditions: Any) -> tuple[str, list[Any]]:
    """{'status': 'pending', 'done': None} -> ("status = $1", ['pending']); None = no filter."""
    clauses, params = [], []
    for column, value in conditions.items():
        if value is not None:
            params.append(value)
            clauses.append(f"{column} = ${len(params)}")
    return " AND ".join(clauses), params


_ID = ("id", lambda m: m.id)


class PostgresProposalRepo:
    def __init__(self, db: Database) -> None:
        self._t = _Table(
            db,
            "proposals",
            Proposal,
            _ID,
            {"status": lambda p: str(p.status), "created_at": lambda p: p.created_at},
        )

    async def add(self, proposal: Proposal) -> None:
        await self._t.put(proposal)

    async def get(self, proposal_id: str) -> Proposal | None:
        return await self._t.get(proposal_id)

    async def find(self, status: ProposalStatus | None = None) -> list[Proposal]:
        where, params = _filters(status=str(status) if status else None)
        return await self._t.select(where, params, "created_at DESC, seq")

    async def update(self, proposal: Proposal) -> None:
        await self._t.put(proposal)


class PostgresReminderRepo:
    def __init__(self, db: Database) -> None:
        self._t = _Table(
            db,
            "reminders",
            Reminder,
            _ID,
            {"status": lambda r: str(r.status), "due_at": lambda r: r.due_at},
        )

    async def add(self, reminder: Reminder) -> None:
        await self._t.put(reminder)

    async def get(self, reminder_id: str) -> Reminder | None:
        return await self._t.get(reminder_id)

    async def find(self, status: ReminderStatus | None = None) -> list[Reminder]:
        where, params = _filters(status=str(status) if status else None)
        return await self._t.select(where, params, "due_at, seq")

    async def due(self, now: datetime) -> list[Reminder]:
        return await self._t.select(
            "status = $1 AND due_at <= $2", [str(ReminderStatus.SCHEDULED), now], "due_at, seq"
        )

    async def update(self, reminder: Reminder) -> None:
        await self._t.put(reminder)


class PostgresTaskRepo:
    def __init__(self, db: Database) -> None:
        self._t = _Table(
            db,
            "tasks",
            Task,
            _ID,
            {
                "horizon": lambda t: str(t.horizon),
                "done": lambda t: t.done,
                "created_at": lambda t: t.created_at,
            },
        )

    async def add(self, task: Task) -> None:
        await self._t.put(task)

    async def get(self, task_id: str) -> Task | None:
        return await self._t.get(task_id)

    async def find(self, horizon: Horizon | None = None, done: bool | None = None) -> list[Task]:
        where, params = _filters(horizon=str(horizon) if horizon else None, done=done)
        return await self._t.select(where, params, "created_at, seq")

    async def update(self, task: Task) -> None:
        await self._t.put(task)


class PostgresFolderRepo:
    def __init__(self, db: Database) -> None:
        self._folders = _Table(db, "folders", Folder, _ID, {"created_at": lambda f: f.created_at})
        self._items = _Table(
            db,
            "items",
            Item,
            _ID,
            {"folder_id": lambda i: i.folder_id, "created_at": lambda i: i.created_at},
        )

    async def add(self, folder: Folder) -> None:
        await self._folders.put(folder)

    async def get(self, folder_id: str) -> Folder | None:
        return await self._folders.get(folder_id)

    async def find(self) -> list[Folder]:
        return await self._folders.select(order="created_at, seq")

    async def add_item(self, item: Item) -> None:
        await self._items.put(item)

    async def find_items(self, folder_id: str) -> list[Item]:
        return await self._items.select("folder_id = $1", [folder_id], "created_at, seq")


class PostgresChatRepo:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._sessions = _Table(
            db, "chat_sessions", ChatSession, _ID, {"created_at": lambda s: s.created_at}
        )
        self._messages = _Table(
            db,
            "chat_messages",
            ChatMessage,
            _ID,
            {"session_id": lambda m: m.session_id, "created_at": lambda m: m.created_at},
        )

    async def add_session(self, session: ChatSession) -> None:
        await self._sessions.put(session)

    async def get_session(self, session_id: str) -> ChatSession | None:
        return await self._sessions.get(session_id)

    async def find_sessions(self) -> list[ChatSession]:
        # most recent activity first; last_message_at lives in the JSONB row (no migration)
        recent = "COALESCE((data->>'last_message_at')::timestamptz, created_at)"
        return await self._sessions.select(order=f"{recent} DESC, seq")

    async def update_session(self, session: ChatSession) -> None:
        await self._sessions.put(session)

    async def delete_session(self, session_id: str) -> bool:
        async with (await self._db.pool()).acquire() as conn, conn.transaction():
            await conn.execute("DELETE FROM chat_messages WHERE session_id = $1", session_id)
            status = await conn.execute("DELETE FROM chat_sessions WHERE id = $1", session_id)
        return bool(status.endswith(" 1"))

    async def add_message(self, message: ChatMessage) -> None:
        await self._messages.put(message)

    async def find_messages(self, session_id: str) -> list[ChatMessage]:
        return await self._messages.select("session_id = $1", [session_id], "created_at, seq")


class PostgresMemoryRepo:
    def __init__(self, db: Database) -> None:
        self._suggestions = _Table(
            db,
            "memory_suggestions",
            MemorySuggestion,
            _ID,
            {"status": lambda s: str(s.status), "created_at": lambda s: s.created_at},
        )
        self._facts = _Table(
            db, "memory_facts", MemoryFact, _ID, {"created_at": lambda f: f.created_at}
        )

    async def add_suggestion(self, suggestion: MemorySuggestion) -> None:
        await self._suggestions.put(suggestion)

    async def get_suggestion(self, suggestion_id: str) -> MemorySuggestion | None:
        return await self._suggestions.get(suggestion_id)

    async def find_suggestions(
        self, status: SuggestionStatus | None = None
    ) -> list[MemorySuggestion]:
        where, params = _filters(status=str(status) if status else None)
        return await self._suggestions.select(where, params, "created_at DESC, seq")

    async def update_suggestion(self, suggestion: MemorySuggestion) -> None:
        await self._suggestions.put(suggestion)

    async def add_fact(self, fact: MemoryFact) -> None:
        await self._facts.put(fact)

    async def find_facts(self) -> list[MemoryFact]:
        return await self._facts.select(order="created_at DESC, seq")

    async def update_fact(self, fact: MemoryFact) -> bool:
        if not await self._facts.exists(fact.id):
            return False  # an update never inserts
        await self._facts.put(fact)
        return True

    async def delete_fact(self, fact_id: str) -> bool:
        return await self._facts.delete(fact_id)


class PostgresPushSubscriptionRepo:
    def __init__(self, db: Database) -> None:
        self._t = _Table(
            db, "push_subscriptions", PushSubscription, ("endpoint", lambda s: s.endpoint)
        )

    async def upsert(self, subscription: PushSubscription) -> None:
        await self._t.put(subscription)

    async def remove(self, endpoint: str) -> bool:
        return await self._t.delete(endpoint)

    async def find(self) -> list[PushSubscription]:
        return await self._t.select()


class PostgresDeliveryRepo:
    def __init__(self, db: Database) -> None:
        self._t = _Table(
            db,
            "deliveries",
            Delivery,
            ("notification_id", lambda d: d.notification_id),
            {"sent_at": lambda d: d.sent_at},
        )

    async def record(self, delivery: Delivery) -> None:
        await self._t.put(delivery)

    async def ack(self, notification_id: str, received_at: datetime) -> bool:
        delivery = await self._t.get(notification_id)
        if delivery is None:
            return False
        await self._t.put(delivery.model_copy(update={"received_at": received_at}))
        return True

    async def find(self) -> list[Delivery]:
        return await self._t.select(order="sent_at, seq")


class PostgresAuditRepo:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._t = _Table(db, "audit", AuditEntry, _ID, {"at": lambda e: e.at})

    async def add(self, entry: AuditEntry) -> None:
        await self._t.put(entry)

    async def find(self, limit: int = 100) -> list[AuditEntry]:
        rows = await (await self._db.pool()).fetch(
            "SELECT data FROM audit ORDER BY seq DESC LIMIT $1", limit
        )
        return [AuditEntry.model_validate_json(r["data"]) for r in rows]


class _Setting(BaseModel):
    key: str
    value: NotificationSettings


class PostgresSettingsRepo:
    def __init__(self, db: Database) -> None:
        self._t = _Table(db, "settings", _Setting, ("key", lambda s: s.key))

    async def get_notification_settings(self) -> NotificationSettings:
        row = await self._t.get("notifications")
        return row.value if row is not None else NotificationSettings()

    async def put_notification_settings(self, settings: NotificationSettings) -> None:
        await self._t.put(_Setting(key="notifications", value=settings))


TABLES = (
    "proposals",
    "reminders",
    "tasks",
    "folders",
    "items",
    "chat_sessions",
    "chat_messages",
    "memory_suggestions",
    "memory_facts",
    "push_subscriptions",
    "deliveries",
    "audit",
    "settings",
)


class PostgresRepositories:
    name = "postgres"
    is_fake = False

    def __init__(self, dsn: str) -> None:
        if not dsn:
            raise ValueError(
                "HELPMATE_REPO=postgres needs HELPMATE_DATABASE_URL (see .env.example) and "
                "`docker compose --env-file .env -f infra/docker-compose.yml up -d postgres`."
            )
        self._dsn = dsn
        self.db = Database(dsn)
        self.proposals = PostgresProposalRepo(self.db)
        self.reminders = PostgresReminderRepo(self.db)
        self.tasks = PostgresTaskRepo(self.db)
        self.folders = PostgresFolderRepo(self.db)
        self.chat = PostgresChatRepo(self.db)
        self.memory = PostgresMemoryRepo(self.db)
        self.push_subscriptions = PostgresPushSubscriptionRepo(self.db)
        self.deliveries = PostgresDeliveryRepo(self.db)
        self.audit = PostgresAuditRepo(self.db)
        self.settings = PostgresSettingsRepo(self.db)

    async def migrate(self) -> None:
        """alembic upgrade head (in a thread: Alembic's async env runs its own event loop)."""
        from alembic import command
        from alembic.config import Config

        config = Config(str(BACKEND_DIR / "alembic.ini"))
        config.attributes["url"] = self._dsn
        await asyncio.to_thread(command.upgrade, config, "head")

    async def startup(self, now: datetime, timezone: str) -> None:
        await self.migrate()
        if not await self.folders.find():  # a brand-new database: same seed as the fakes
            await InMemoryRepositories.seed(self, now, timezone)  # type: ignore[arg-type]

    async def truncate(self) -> None:
        """Tests only: empty every table."""
        await (await self.db.pool()).execute(f"TRUNCATE {', '.join(TABLES)}")

    async def close(self) -> None:
        await self.db.close()
