"""Port contract tests for the persistence layer.

Every implementation of `Repositories` must pass these. Workstream B: add a "postgres" factory
(skipped unless HELPMATE_TEST_DATABASE_URL is set) and the same tests run against Postgres.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from helpmate.adapters.fakes.memory_repos import InMemoryRepositories
from helpmate.domain.models import (
    Actor,
    AuditEntry,
    Delivery,
    NotificationKind,
    Proposal,
    ProposalStatus,
    PushKeys,
    PushSubscription,
    Reminder,
    ReminderStatus,
    new_id,
)
from helpmate.domain.ports import Repositories

FACTORIES: dict[str, Callable[[], Repositories]] = {
    "memory": InMemoryRepositories,
}

NOW = datetime(2026, 10, 5, 16, 0, tzinfo=UTC)


@pytest.fixture(params=sorted(FACTORIES))
def repos(request) -> Repositories:
    return FACTORIES[request.param]()


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
