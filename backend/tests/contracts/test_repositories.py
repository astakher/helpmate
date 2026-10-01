"""Port contract tests for the persistence layer.

Every implementation of `Repositories` must pass these. "postgres" (stand-in for Workstream B)
runs only when HELPMATE_TEST_DATABASE_URL points at a THROWAWAY database (every table is emptied
before each test), e.g. postgresql://helpmate:<password>@127.0.0.1:5432/helpmate_test.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta

import pytest

from helpmate.adapters.fakes.memory_repos import InMemoryRepositories
from helpmate.domain.models import (
    Actor,
    AuditEntry,
    ChatMessage,
    ChatSession,
    Delivery,
    MemoryFact,
    NotificationKind,
    NotificationSettings,
    Proposal,
    ProposalStatus,
    PushKeys,
    PushSubscription,
    Reminder,
    ReminderStatus,
    Role,
    new_id,
)
from helpmate.domain.ports import Repositories

TEST_DATABASE_URL = os.environ.get("HELPMATE_TEST_DATABASE_URL", "")


def _postgres() -> Repositories:
    from helpmate.adapters.postgres_repos import PostgresRepositories

    return PostgresRepositories(TEST_DATABASE_URL)


FACTORIES: dict[str, Callable[[], Repositories]] = {
    "memory": InMemoryRepositories,
    "postgres": _postgres,
}

NOW = datetime(2026, 10, 5, 16, 0, tzinfo=UTC)
_migrated = False


@pytest.fixture(params=sorted(FACTORIES))
async def repos(request) -> AsyncIterator[Repositories]:
    global _migrated
    if request.param == "postgres" and not TEST_DATABASE_URL:
        pytest.skip("set HELPMATE_TEST_DATABASE_URL to run the contract suite against Postgres")
    repositories = FACTORIES[request.param]()
    if request.param == "postgres":
        if not _migrated:
            await repositories.migrate()
            _migrated = True
        await repositories.truncate()
    yield repositories
    if request.param == "postgres":
        await repositories.close()


def _reminder(minutes: int, status: ReminderStatus = ReminderStatus.SCHEDULED) -> Reminder:
    return Reminder(
        id=new_id(),
        text=f"in {minutes}",
        due_at=NOW + timedelta(minutes=minutes),
        status=status,
        created_at=NOW,
    )


async def test_due_returns_only_scheduled_reminders_at_or_before_now(repos):
    past, future = _reminder(-5), _reminder(5)
    cancelled = _reminder(-10, ReminderStatus.CANCELLED)
    for r in (past, future, cancelled):
        await repos.reminders.add(r)
    assert [r.id for r in await repos.reminders.due(NOW)] == [past.id]


async def test_returned_models_are_copies(repos):
    reminder = _reminder(1)
    await repos.reminders.add(reminder)
    reminder.text = "mutated after add"
    fetched = await repos.reminders.get(reminder.id)
    assert fetched is not None and fetched.text == "in 1"
    fetched.text = "mutated after get"
    assert (await repos.reminders.get(reminder.id)).text == "in 1"


async def test_proposals_filter_by_status_newest_first(repos):
    for i, status in enumerate([ProposalStatus.PENDING, ProposalStatus.EXECUTED]):
        await repos.proposals.add(
            Proposal(
                id=f"p{i}",
                tool="create_task",
                title="t",
                summary="s",
                args={},
                status=status,
                created_at=NOW + timedelta(seconds=i),
            )
        )
    assert [p.id for p in await repos.proposals.find()] == ["p1", "p0"]
    assert [p.id for p in await repos.proposals.find(ProposalStatus.PENDING)] == ["p0"]


async def test_push_subscriptions_upsert_by_endpoint(repos):
    sub = PushSubscription(
        endpoint="https://push.example/1", keys=PushKeys(p256dh="k", auth="a"), created_at=NOW
    )
    await repos.push_subscriptions.upsert(sub)
    await repos.push_subscriptions.upsert(sub.model_copy(update={"user_agent": "phone"}))
    [stored] = await repos.push_subscriptions.find()
    assert stored.user_agent == "phone"
    assert await repos.push_subscriptions.remove(sub.endpoint)
    assert not await repos.push_subscriptions.remove(sub.endpoint)


async def test_delivery_ack(repos):
    await repos.deliveries.record(
        Delivery(notification_id="n1", kind=NotificationKind.REMINDER, due_at=NOW, sent_at=NOW)
    )
    assert await repos.deliveries.ack("n1", NOW + timedelta(seconds=3))
    assert not await repos.deliveries.ack("missing", NOW)
    [delivery] = await repos.deliveries.find()
    assert delivery.received_at == NOW + timedelta(seconds=3)


async def test_audit_is_newest_first_and_limited(repos):
    for i in range(5):
        await repos.audit.add(
            AuditEntry(id=str(i), at=NOW + timedelta(seconds=i), actor=Actor.SYSTEM, action="x")
        )
    assert [e.id for e in await repos.audit.find(limit=2)] == ["4", "3"]


async def test_memory_facts_update_and_delete(repos):
    fact = MemoryFact(id="f1", text="my advisor is Dr. Lee", source="chat:s1", created_at=NOW)
    await repos.memory.add_fact(fact)
    assert await repos.memory.update_fact(fact.model_copy(update={"text": "advisor: Dr. Li"}))
    [stored] = await repos.memory.find_facts()
    assert stored.text == "advisor: Dr. Li" and stored.source == "chat:s1"
    missing = fact.model_copy(update={"id": "nope"})
    assert not await repos.memory.update_fact(missing)
    assert await repos.memory.find_facts() == [stored]  # an update never inserts
    assert await repos.memory.delete_fact("f1") and not await repos.memory.delete_fact("f1")


async def test_notification_settings_default_then_round_trip(repos):
    assert await repos.settings.get_notification_settings() == NotificationSettings()
    changed = NotificationSettings(max_per_hour=2, private_previews=True)
    await repos.settings.put_notification_settings(changed)
    assert await repos.settings.get_notification_settings() == changed


async def test_chat_sessions_order_by_activity_update_and_delete(repos):
    older = ChatSession(id="s1", created_at=NOW)
    newer = ChatSession(id="s2", created_at=NOW + timedelta(minutes=1))
    await repos.chat.add_session(older)
    await repos.chat.add_session(newer)
    for session_id, minute in (("s1", 2), ("s2", 3)):
        await repos.chat.add_message(
            ChatMessage(
                id=f"m-{session_id}",
                session_id=session_id,
                role=Role.USER,
                text="hi",
                created_at=NOW + timedelta(minutes=minute),
            )
        )
    assert [s.id for s in await repos.chat.find_sessions()] == ["s2", "s1"]  # newest first

    # a message in the older chat moves it to the top
    await repos.chat.update_session(
        older.model_copy(update={"title": "hi", "last_message_at": NOW + timedelta(minutes=5)})
    )
    assert [s.id for s in await repos.chat.find_sessions()] == ["s1", "s2"]
    assert (await repos.chat.get_session("s1")).title == "hi"

    assert await repos.chat.delete_session("s1")
    assert await repos.chat.get_session("s1") is None
    assert await repos.chat.find_messages("s1") == []
    assert [m.id for m in await repos.chat.find_messages("s2")] == ["m-s2"]  # others untouched
    assert not await repos.chat.delete_session("s1")


def _axis(i: int) -> list[float]:
    vector = [0.0] * 768  # nomic-embed-text's size, as the pgvector column expects
    vector[i] = 1.0
    return vector


async def test_documents_search_by_similarity_and_delete_with_their_passages(repos):
    from helpmate.domain.models import Document, DocumentPassage

    def doc(doc_id: str, minutes: int) -> Document:
        return Document(
            id=doc_id,
            name=f"{doc_id}.pdf",
            content_type="application/pdf",
            size=10,
            storage_key=f"documents/{doc_id}",
            created_at=NOW + timedelta(minutes=minutes),
        )

    def passage(pid: str, doc_id: str, index: int) -> DocumentPassage:
        return DocumentPassage(
            id=pid, document_id=doc_id, document_name=f"{doc_id}.pdf", page=1, index=index, text=pid
        )

    await repos.documents.add(doc("syllabus", 0))
    await repos.documents.add(doc("lease", 1))
    await repos.documents.add_passages(
        [passage("s1", "syllabus", 0), passage("s2", "syllabus", 1), passage("l1", "lease", 0)],
        [_axis(0), _axis(1), [0.6, 0.8] + [0.0] * 766],
    )
    assert [d.id for d in await repos.documents.find()] == ["lease", "syllabus"]  # newest first
    hits = await repos.documents.search(_axis(1), limit=2)
    assert [p.id for p, _ in hits] == ["s2", "l1"]
    assert round(hits[0][1], 3) == 1.0 and round(hits[1][1], 3) == 0.8  # cosine similarity

    assert await repos.documents.delete("syllabus")
    assert await repos.documents.get("syllabus") is None
    assert [p.id for p, _ in await repos.documents.search(_axis(0), limit=5)] == ["l1"]
    assert not await repos.documents.delete("syllabus")
