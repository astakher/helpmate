"""DevScheduler (HELPMATE_SCHEDULER=dev): an asyncio loop that polls for due reminders.

Stand-in for Workstream B's Postgres job queue. It does not survive restarts, has no retries and
ignores recurrence (a recurring reminder fires once). Those are exactly the things the real
scheduler adds.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from helpmate.domain.models import (
    Delivery,
    Notification,
    NotificationKind,
    Reminder,
    ReminderStatus,
    new_id,
)
from helpmate.domain.ports import Clock, NotifierPort, Repositories

log = logging.getLogger("helpmate.scheduler")


class DevScheduler:
    name = "dev"
    is_fake = True

    def __init__(
        self,
        repos: Repositories,
        notifier: NotifierPort,
        clock: Clock,
        tick_seconds: float = 5.0,
    ) -> None:
        self._repos = repos
        self._notifier = notifier
        self._clock = clock
        self._tick_seconds = tick_seconds
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="dev-scheduler")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def schedule(self, reminder: Reminder) -> None:
        log.info("scheduled reminder %s for %s", reminder.id, reminder.due_at.isoformat())

    async def cancel(self, reminder_id: str) -> None:
        reminder = await self._repos.reminders.get(reminder_id)
        if reminder is not None and reminder.status == ReminderStatus.SCHEDULED:
            reminder.status = ReminderStatus.CANCELLED
            await self._repos.reminders.update(reminder)

    async def tick(self) -> int:
        """Fire every due reminder once. Returns how many fired."""
        fired = 0
        for reminder in await self._repos.reminders.due(self._clock.now()):
            notification = Notification(
                id=new_id(),
                kind=NotificationKind.REMINDER,
                title="Reminder",
                body=reminder.text,
                url="/reminders",
                tag=f"reminder-{reminder.id}",
                urgent=True,
                due_at=reminder.due_at,
            )
            # record before sending so a fast service-worker ack always finds the row
            await self._repos.deliveries.record(
                Delivery(
                    notification_id=notification.id,
                    kind=notification.kind,
                    due_at=reminder.due_at,
                    sent_at=self._clock.now(),
                )
            )
            await self._notifier.notify(notification)
            reminder.status = ReminderStatus.SENT
            reminder.sent_at = self._clock.now()
            await self._repos.reminders.update(reminder)
            fired += 1
        return fired

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                log.exception("scheduler tick failed")
            await asyncio.sleep(self._tick_seconds)
