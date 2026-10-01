# Stand-in for Workstream B - not part of the Part C deliverable
"""JobScheduler: fires reminders (and other jobs) from a job queue (worker/jobs.py).

- Each reminder occurrence is one job, id "reminder:<id>:<due_at>", so queueing it twice is a
  no-op. schedule() queues it and wakes the loop; every tick also sweeps the reminders table for
  due ones without a job, so a reminder is never missed (e.g. one created while the API was down).
- The loop sleeps until the next job is due (at most MAX_SLEEP), not a fixed 5 s poll, and
  schedule() wakes it early: reminders fire within a fraction of a second of their time.
- A job whose handler raises is retried with backoff (30 s, 2 min, 10 min, 30 min), then kept as
  failed. A push that reached no device although some are subscribed counts as a failure.
- A reminder that fires more than LATE_AFTER late (the laptop was off) says when it was due.
- Other job kinds (e.g. the evening check-in) plug in with register(kind, handler).

HELPMATE_SCHEDULER=dev uses the in-memory store (adapters/fakes/dev_scheduler.py); =pg the
Postgres one, which survives restarts.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from helpmate.domain.models import (
    Delivery,
    Notification,
    NotificationKind,
    Reminder,
    ReminderStatus,
    new_id,
)
from helpmate.domain.ports import Clock, NotifierPort, Repositories
from helpmate.worker.jobs import BACKOFF, MAX_ATTEMPTS, Job, JobStore
from helpmate.worker.recurrence import InvalidRecurrence, next_occurrence

log = logging.getLogger("helpmate.scheduler")

MAX_SLEEP = 30.0  # seconds; also how often the sweep runs when nothing is due
LATE_AFTER = timedelta(minutes=10)
REMINDER = "reminder"

Handler = Callable[[Job], Awaitable[None]]


class DeliveryFailed(RuntimeError):
    """The push reached none of the subscribed devices: worth retrying."""


def reminder_job(reminder: Reminder) -> Job:
    due = reminder.due_at.isoformat()
    return Job(
        id=f"{REMINDER}:{reminder.id}:{due}",
        kind=REMINDER,
        run_at=reminder.due_at,
        payload={"reminder_id": reminder.id, "due_at": due},
    )


class JobScheduler:
    def __init__(
        self,
        store: JobStore,
        repos: Repositories,
        notifier: NotifierPort,
        clock: Clock,
        tz: ZoneInfo | None = None,
        name: str = "jobs",
        is_fake: bool = False,
    ) -> None:
        self._store = store
        self._repos = repos
        self._notifier = notifier
        self._clock = clock
        self._tz = tz or ZoneInfo("UTC")  # the owner's zone: recurrences follow their wall clock
        self.name = name
        self.is_fake = is_fake
        self._handlers: dict[str, Handler] = {REMINDER: self._fire_reminder}
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def store(self) -> JobStore:
        return self._store

    def register(self, kind: str, handler: Handler) -> None:
        self._handlers[kind] = handler

    async def enqueue(self, job: Job) -> None:
        """Queue any job kind (idempotent by job id) and wake the loop."""
        await self._store.put(job)
        self._wake.set()

    # --- SchedulerPort --------------------------------------------------------------------

    async def start(self) -> None:
        if self._task is None:
            # reminders scheduled before this worker existed (or before a restart of the dev
            # store) get their jobs now, so the loop wakes on time instead of at the next sweep
            for reminder in await self._repos.reminders.find(ReminderStatus.SCHEDULED):
                await self._store.put(reminder_job(reminder))
            self._task = asyncio.create_task(self._loop(), name=f"{self.name}-scheduler")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def schedule(self, reminder: Reminder) -> None:
        await self.enqueue(reminder_job(reminder))
        log.info("scheduled reminder %s for %s", reminder.id, reminder.due_at.isoformat())

    async def cancel(self, reminder_id: str) -> None:
        # the queued job finds the reminder cancelled and does nothing
        reminder = await self._repos.reminders.get(reminder_id)
        if reminder is not None and reminder.status == ReminderStatus.SCHEDULED:
            reminder.status = ReminderStatus.CANCELLED
            await self._repos.reminders.update(reminder)

    # --- the work ---------------------------------------------------------------------------

    async def tick(self) -> int:
        """Run every due job once. Returns how many finished successfully."""
        now = self._clock.now()
        for reminder in await self._repos.reminders.due(now):  # the sweep
            await self._store.put(reminder_job(reminder))
        done = 0
        for job in await self._store.claim(now):
            handler = self._handlers.get(job.kind)
            try:
                if handler is None:
                    raise LookupError(f"no handler for job kind {job.kind!r}")
                await handler(job)
            except Exception as exc:
                await self._failed(job, exc)
                continue
            await self._store.complete(job.id)
            done += 1
        return done

    async def _failed(self, job: Job, exc: Exception) -> None:
        error = f"{exc.__class__.__name__}: {exc}"
        if job.attempts >= MAX_ATTEMPTS:
            log.error("job %s failed for good after %d attempts: %s", job.id, job.attempts, error)
            await self._store.fail(job.id, error)
            return
        delay = BACKOFF[min(job.attempts, len(BACKOFF)) - 1]
        log.warning(
            "job %s failed (attempt %d), retrying in %s: %s", job.id, job.attempts, delay, error
        )
        await self._store.retry(job.id, self._clock.now() + delay, error)

    async def _fire_reminder(self, job: Job) -> None:
        reminder = await self._repos.reminders.get(job.payload["reminder_id"])
        if (
            reminder is None
            or reminder.status != ReminderStatus.SCHEDULED
            or reminder.due_at.isoformat() != job.payload["due_at"]
        ):
            return  # cancelled, already sent, or moved to another time (a newer job has it)
        now = self._clock.now()
        body = reminder.text
        if now - reminder.due_at > LATE_AFTER:
            body += f" (was due {reminder.due_at.astimezone(self._tz):%a %H:%M})"
        notification = Notification(
            id=new_id(),
            kind=NotificationKind.REMINDER,
            title="Reminder",
            body=body,
            url="/reminders",
            tag=f"reminder-{reminder.id}",  # a retry replaces, not duplicates, it on the phone
            urgent=True,
            due_at=reminder.due_at,
        )
        # record before sending so a fast service-worker ack always finds the row
        await self._repos.deliveries.record(
            Delivery(
                notification_id=notification.id,
                kind=notification.kind,
                due_at=reminder.due_at,
                sent_at=now,
            )
        )
        result = await self._notifier.notify(notification)
        if result.failed and not result.delivered and not result.deferred:
            raise DeliveryFailed(result.detail or "push failed on every device")
        reminder.sent_at = now
        following = self._next(reminder)
        if following is None:
            reminder.status = ReminderStatus.SENT
        else:  # recurring: the same reminder waits for its next occurrence
            reminder.due_at = following
            log.info("recurring reminder %s next at %s", reminder.id, following.isoformat())
        await self._repos.reminders.update(reminder)
        if following is not None:
            await self._store.put(reminder_job(reminder))

    def _next(self, reminder: Reminder) -> datetime | None:
        if not reminder.recurrence:
            return None
        try:
            return next_occurrence(
                reminder.recurrence, reminder.due_at, self._tz, after=self._clock.now()
            )
        except InvalidRecurrence as exc:
            log.warning("reminder %s fires once: %s", reminder.id, exc)
            return None

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
                upcoming = await self._store.next_run_at()
            except Exception:
                log.exception("scheduler tick failed")
                upcoming = None
            delay = MAX_SLEEP
            if upcoming is not None:
                delay = min(MAX_SLEEP, max(0.05, (upcoming - self._clock.now()).total_seconds()))
            self._wake.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), delay)
