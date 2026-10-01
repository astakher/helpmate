# Stand-in for Workstream B - not part of the Part C deliverable
"""JobScheduler: reminders as jobs, retries with backoff, late reminders, other job kinds."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from helpmate.adapters.clock import FakeClock, SystemClock
from helpmate.adapters.fakes.memory_repos import InMemoryRepositories
from helpmate.domain.models import DeliveryResult, Notification, Reminder, ReminderStatus, new_id
from helpmate.worker.jobs import MAX_ATTEMPTS, InMemoryJobStore, Job
from helpmate.worker.scheduler import JobScheduler

TZ = ZoneInfo("America/Toronto")
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=TZ)


class Phone:
    """A notifier whose push fails the first `failures` times (subscribed but unreachable)."""

    name = "phone"
    is_fake = True

    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.shown: list[Notification] = []

    async def notify(self, notification: Notification) -> DeliveryResult:
        if self.failures:
            self.failures -= 1
            return DeliveryResult(
                notification_id=notification.id, delivered=0, failed=1, detail="0/1 devices"
            )
        self.shown.append(notification)
        return DeliveryResult(notification_id=notification.id, delivered=1)


def reminder(minutes: int, text: str = "stretch", **extra) -> Reminder:
    return Reminder(
        id=new_id(), text=text, due_at=NOW + timedelta(minutes=minutes), created_at=NOW, **extra
    )


def scheduler(phone: Phone, clock=None, repos=None) -> tuple[JobScheduler, InMemoryRepositories]:
    repos = repos or InMemoryRepositories()
    clock = clock or FakeClock(NOW)
    return JobScheduler(InMemoryJobStore(), repos, phone, clock, TZ), repos


async def test_a_scheduled_reminder_fires_once_when_due():
    phone = Phone()
    clock = FakeClock(NOW)
    jobs, repos = scheduler(phone, clock)
    r = reminder(1)
    await repos.reminders.add(r)
    await jobs.schedule(r)
    await jobs.schedule(r)  # queued twice: still one job
    assert await jobs.tick() == 0
    clock.advance(minutes=1)
    assert await jobs.tick() == 1
    assert await jobs.tick() == 0
    assert [n.body for n in phone.shown] == ["stretch"]
    assert (await repos.reminders.get(r.id)).status == ReminderStatus.SENT


async def test_a_due_reminder_without_a_job_is_swept_up():
    phone = Phone()
    jobs, repos = scheduler(phone)
    await repos.reminders.add(reminder(-1))  # e.g. created while the API was down
    assert await jobs.tick() == 1
    assert len(phone.shown) == 1


async def test_a_failed_push_is_retried_with_backoff_then_delivered():
    phone = Phone(failures=2)
    clock = FakeClock(NOW)
    jobs, repos = scheduler(phone, clock)
    r = reminder(0)
    await repos.reminders.add(r)
    assert await jobs.tick() == 0  # attempt 1 fails
    assert (await repos.reminders.get(r.id)).status == ReminderStatus.SCHEDULED
    clock.advance(seconds=29)
    assert await jobs.tick() == 0  # not yet: the first retry waits 30 s
    clock.advance(seconds=1)
    assert await jobs.tick() == 0  # attempt 2 fails
    clock.advance(minutes=2)
    assert await jobs.tick() == 1  # attempt 3 gets through
    assert len(phone.shown) == 1
    assert (await repos.reminders.get(r.id)).status == ReminderStatus.SENT


async def test_after_max_attempts_the_job_is_kept_as_failed():
    phone = Phone(failures=99)
    clock = FakeClock(NOW)
    jobs, repos = scheduler(phone, clock)
    await repos.reminders.add(reminder(0))
    for _ in range(MAX_ATTEMPTS):
        await jobs.tick()
        clock.advance(hours=1)
    [failed] = await jobs.store.failed()
    assert failed.attempts == MAX_ATTEMPTS and "0/1 devices" in failed.last_error
    assert await jobs.tick() == 0  # and it isn't re-queued by the sweep


async def test_no_devices_subscribed_is_not_a_failure():
    class NoDevices(Phone):
        async def notify(self, notification):
            return DeliveryResult(notification_id=notification.id, delivered=0, detail="none")

    jobs, repos = scheduler(NoDevices())
    r = reminder(0)
    await repos.reminders.add(r)
    assert await jobs.tick() == 1
    assert (await repos.reminders.get(r.id)).status == ReminderStatus.SENT


async def test_a_late_reminder_says_when_it_was_due():
    phone = Phone()
    jobs, repos = scheduler(phone)
    await repos.reminders.add(reminder(-45, "call mom"))  # the laptop was off
    await jobs.tick()
    assert phone.shown[0].body == "call mom (was due Mon 11:15)"


async def test_cancelled_and_moved_reminders_dont_fire_from_old_jobs():
    phone = Phone()
    clock = FakeClock(NOW)
    jobs, repos = scheduler(phone, clock)
    cancelled, moved = reminder(1, "cancelled"), reminder(1, "moved")
    for r in (cancelled, moved):
        await repos.reminders.add(r)
        await jobs.schedule(r)
    await jobs.cancel(cancelled.id)
    moved.due_at = NOW + timedelta(minutes=30)
    await repos.reminders.update(moved)
    await jobs.schedule(moved)
    clock.advance(minutes=1)
    await jobs.tick()
    assert phone.shown == []  # the old "moved" job found a different due time
    clock.advance(minutes=29)
    await jobs.tick()
    assert [n.body for n in phone.shown] == ["moved"]


async def test_a_recurring_reminder_queues_its_next_occurrence():
    phone = Phone()
    clock = FakeClock(NOW)
    jobs, repos = scheduler(phone, clock)
    r = reminder(0, "vitamins", recurrence="FREQ=DAILY")
    await repos.reminders.add(r)
    await jobs.tick()
    assert (await jobs.store.next_run_at()) == NOW + timedelta(days=1)
    clock.advance(days=1)
    assert await jobs.tick() == 1
    assert len(phone.shown) == 2


async def test_other_job_kinds_run_through_registered_handlers():
    ran: list[dict] = []

    async def handler(job: Job) -> None:
        ran.append(job.payload)

    jobs, _ = scheduler(Phone())
    jobs.register("checkin", handler)
    await jobs.enqueue(Job(id="checkin:2026-10-05", kind="checkin", run_at=NOW, payload={"d": 1}))
    assert await jobs.tick() == 1
    assert ran == [{"d": 1}]


async def test_the_loop_wakes_for_a_new_reminder_instead_of_polling():
    phone = Phone()
    clock = SystemClock()
    repos = InMemoryRepositories()
    jobs = JobScheduler(InMemoryJobStore(), repos, phone, clock, TZ)
    await jobs.start()
    try:
        await asyncio.sleep(0.1)  # the loop is now asleep (nothing queued: up to 30 s)
        r = Reminder(
            id=new_id(),
            text="now",
            due_at=clock.now() + timedelta(milliseconds=200),
            created_at=datetime.now(UTC),
        )
        await repos.reminders.add(r)
        await jobs.schedule(r)
        for _ in range(40):
            if phone.shown:
                break
            await asyncio.sleep(0.05)
        assert [n.body for n in phone.shown] == ["now"]  # well under the old 5 s poll
    finally:
        await jobs.stop()
