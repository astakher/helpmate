# Stand-in for Workstream B - not part of the Part C deliverable
"""The evening check-in: a daily push at the owner's chosen time (NotificationSettings.checkin_at).

"3 tasks left this week. Tomorrow: 4 events (first at 9:00), 2 reminders." It's a job on the
JobScheduler: every tick, the sweep queues the next occurrence from the current settings (job id
"checkin:<date>:<HH:MM>", so queueing is idempotent and a changed time gets its own job); the
handler checks the settings again, so a job queued before the owner turned it off or changed the
time does nothing. A check-in that is more than STALE_AFTER late (the laptop was off all evening)
is skipped rather than sent in the middle of the night.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from helpmate.domain.models import (
    Horizon,
    Notification,
    NotificationKind,
    ProposalStatus,
    ReminderStatus,
    new_id,
)
from helpmate.domain.ports import CalendarPort, Clock, NotifierPort, Repositories
from helpmate.worker.jobs import Job
from helpmate.worker.scheduler import DeliveryFailed, JobScheduler

log = logging.getLogger("helpmate.checkin")

CHECKIN = "checkin"
STALE_AFTER = timedelta(hours=2)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


class EveningCheckIn:
    def __init__(
        self,
        scheduler: JobScheduler,
        repos: Repositories,
        calendar: CalendarPort,
        notifier: NotifierPort,
        clock: Clock,
        tz: ZoneInfo,
    ) -> None:
        self._scheduler = scheduler
        self._repos = repos
        self._calendar = calendar
        self._notifier = notifier
        self._clock = clock
        self._tz = tz

    def install(self) -> None:
        self._scheduler.register(CHECKIN, self._run, sweep=self.ensure_queued)

    async def ensure_queued(self) -> None:
        at = (await self._repos.settings.get_notification_settings()).checkin_at
        if at is None:
            return
        local_now = self._clock.now().astimezone(self._tz)
        when = datetime.combine(local_now.date(), at, tzinfo=self._tz)
        if when <= local_now:
            when = datetime.combine(local_now.date() + timedelta(days=1), at, tzinfo=self._tz)
        await self._scheduler.store.put(
            Job(
                id=f"{CHECKIN}:{when.date().isoformat()}:{at:%H:%M}",
                kind=CHECKIN,
                run_at=when,
                payload={"date": when.date().isoformat(), "at": f"{at:%H:%M}"},
            )
        )

    async def _run(self, job: Job) -> None:
        at = (await self._repos.settings.get_notification_settings()).checkin_at
        if at is None or f"{at:%H:%M}" != job.payload["at"]:
            return  # turned off, or moved to another time (that one has its own job)
        due = datetime.combine(
            date.fromisoformat(job.payload["date"]), time.fromisoformat(job.payload["at"]), self._tz
        )
        if self._clock.now() - due > STALE_AFTER:
            log.info(
                "skipping the %s check-in: %s late", job.payload["date"], self._clock.now() - due
            )
            return
        notification = Notification(
            id=new_id(),
            kind=NotificationKind.BRIEF,
            title="Evening check-in",
            body=await self.summary(),
            url="/week",
            tag="checkin",  # tonight's replaces yesterday's on the phone
            urgent=False,
            due_at=due,
        )
        result = await self._notifier.notify(notification)
        if result.failed and not result.delivered and not result.deferred:
            raise DeliveryFailed(result.detail or "push failed on every device")

    async def summary(self) -> str:
        """The check-in text: what's left this week, and what tomorrow holds."""
        local_now = self._clock.now().astimezone(self._tz)
        tomorrow = datetime.combine(local_now.date() + timedelta(days=1), time(0), tzinfo=self._tz)
        day_after = tomorrow + timedelta(days=1)

        tasks = await self._repos.tasks.find(Horizon.WEEK, done=False)
        reminders = [
            r
            for r in await self._repos.reminders.find(ReminderStatus.SCHEDULED)
            if tomorrow <= r.due_at < day_after
        ]
        pending = await self._repos.proposals.find(ProposalStatus.PENDING)
        try:
            events = await self._calendar.list_events(tomorrow, day_after)
            timed = sorted(
                (e for e in events if e.end - e.start < timedelta(days=1)), key=lambda e: e.start
            )
        except Exception:  # e.g. Google signed out: say what we know
            log.warning("check-in without the calendar", exc_info=True)
            events, timed = None, []

        parts = [
            f"{_plural(len(tasks), 'task')} left this week."
            if tasks
            else "No tasks left this week."
        ]
        tomorrow_bits = []
        if events:
            first = f" (first at {timed[0].start.astimezone(self._tz):%H:%M})" if timed else ""
            tomorrow_bits.append(_plural(len(events), "event") + first)
        if reminders:
            tomorrow_bits.append(_plural(len(reminders), "reminder"))
        if tomorrow_bits:
            parts.append("Tomorrow: " + ", ".join(tomorrow_bits) + ".")
        elif events is not None:
            parts.append("Tomorrow is clear.")
        if pending:
            parts.append(f"{_plural(len(pending), 'card')} waiting for your approval.")
        return " ".join(parts)
