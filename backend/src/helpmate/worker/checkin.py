# Stand-in for Workstream B - not part of the Part C deliverable
"""Scheduled summaries pushed to the phone, each on when the owner turns it on in Settings:

- the evening check-in (NotificationSettings.checkin_at): "3 tasks left this week. Tomorrow: 4
  events (first at 9:00), 2 reminders."
- the morning brief (morning_brief_at): "Today: 3 events (first at 09:30), 2 reminders. 5 unread
  emails. 4 tasks left this week."
- the weekly review (weekly_review_day at weekly_review_at): "Last 7 days: 5 tasks done, 3
  reminders sent, 2 actions approved. Still open: 3 tasks (1 overdue). Next 7 days: 8 events."

Each is a job on the JobScheduler: every tick, the sweep queues the next occurrence from the
current settings (job id "<kind>:<date>:<HH:MM>", so queueing is idempotent and a changed time
gets its own job); the handler checks the settings again, so a job queued before the owner turned
it off or changed the time (or day) does nothing. One more than STALE_AFTER late (the laptop was
off) is skipped rather than sent at an odd hour.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from helpmate.agent.triage import UNREAD_PRIMARY
from helpmate.domain.models import (
    Horizon,
    Notification,
    NotificationKind,
    NotificationSettings,
    ProposalStatus,
    ReminderStatus,
    Task,
    new_id,
)
from helpmate.domain.ports import CalendarPort, Clock, MailPort, NotifierPort, Repositories
from helpmate.worker.jobs import Job
from helpmate.worker.scheduler import DeliveryFailed, JobScheduler

log = logging.getLogger("helpmate.checkin")

CHECKIN = "checkin"
BRIEF = "brief"
REVIEW = "review"
STALE_AFTER = timedelta(hours=2)
CALENDAR_SECONDS = 8.0  # a slow Google answer mustn't hold up a summary
UNREAD_COUNTED = 20  # "20+ unread emails" beyond this


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


class _ScheduledPush:
    """A summary pushed at the owner's chosen local time: daily, or on one weekday."""

    kind: str
    title: str
    url: str  # what tapping it opens
    tag: str  # the newest replaces the last one on the phone

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
        self._scheduler.register(self.kind, self._run, sweep=self.ensure_queued)

    def when(self, settings: NotificationSettings) -> tuple[time | None, int | None]:
        """(local time, weekday Monday=0 or None for every day); no time = off."""
        raise NotImplementedError

    async def summary(self) -> str:
        raise NotImplementedError

    async def ensure_queued(self) -> None:
        at, weekday = self.when(await self._repos.settings.get_notification_settings())
        if at is None:
            return
        local_now = self._clock.now().astimezone(self._tz)
        day = local_now.date()
        when = datetime.combine(day, at, tzinfo=self._tz)
        while when <= local_now or (weekday is not None and day.weekday() != weekday):
            day += timedelta(days=1)
            when = datetime.combine(day, at, tzinfo=self._tz)
        await self._scheduler.store.put(
            Job(
                id=f"{self.kind}:{day.isoformat()}:{at:%H:%M}",
                kind=self.kind,
                run_at=when,
                payload={"date": day.isoformat(), "at": f"{at:%H:%M}"},
            )
        )

    async def _run(self, job: Job) -> None:
        at, weekday = self.when(await self._repos.settings.get_notification_settings())
        day = date.fromisoformat(job.payload["date"])
        if at is None or f"{at:%H:%M}" != job.payload["at"]:
            return  # turned off, or moved to another time (that one has its own job)
        if weekday is not None and day.weekday() != weekday:
            return  # moved to another day
        due = datetime.combine(day, time.fromisoformat(job.payload["at"]), self._tz)
        if self._clock.now() - due > STALE_AFTER:
            log.info("skipping the %s %s: %s late", day, self.kind, self._clock.now() - due)
            return
        notification = Notification(
            id=new_id(),
            kind=NotificationKind.BRIEF,
            title=self.title,
            body=await self.summary(),
            url=self.url,
            tag=self.tag,
            urgent=False,
            due_at=due,
        )
        result = await self._notifier.notify(notification)
        if result.failed and not result.delivered and not result.deferred:
            raise DeliveryFailed(result.detail or "push failed on every device")

    async def _events(self, start: datetime, end: datetime) -> tuple[list, str | None]:
        """The calendar between start and end, or why it couldn't be read."""
        try:
            return await asyncio.wait_for(
                self._calendar.list_events(start, end), CALENDAR_SECONDS
            ), None
        except Exception as exc:  # e.g. Google signed out: say what we know
            log.warning("%s without the calendar", self.kind, exc_info=True)
            return [], str(exc) or exc.__class__.__name__

    def _first(self, events: list) -> str:
        timed = sorted(
            (e for e in events if e.end - e.start < timedelta(days=1)), key=lambda e: e.start
        )
        return f" (first at {timed[0].start.astimezone(self._tz):%H:%M})" if timed else ""


class EveningCheckIn(_ScheduledPush):
    kind, title, url, tag = CHECKIN, "Evening check-in", "/week", "checkin"

    def when(self, settings: NotificationSettings) -> tuple[time | None, int | None]:
        return settings.checkin_at, None

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
        events, error = await self._events(tomorrow, day_after)

        parts = [
            f"{_plural(len(tasks), 'task')} left this week."
            if tasks
            else "No tasks left this week."
        ]
        tomorrow_bits = []
        if events:
            tomorrow_bits.append(_plural(len(events), "event") + self._first(events))
        if reminders:
            tomorrow_bits.append(_plural(len(reminders), "reminder"))
        if tomorrow_bits:
            parts.append("Tomorrow: " + ", ".join(tomorrow_bits) + ".")
        elif error is None:
            parts.append("Tomorrow is clear.")
        if pending:
            parts.append(f"{_plural(len(pending), 'card')} waiting for your approval.")
        return " ".join(parts)


class MorningBrief(_ScheduledPush):
    """Today at a glance, first thing: events, reminders, unread mail (Primary tab), the week's
    tasks and what's waiting for approval. Tapping it opens the Today page."""

    kind, title, url, tag = BRIEF, "Good morning", "/today", "brief"

    def __init__(
        self,
        scheduler: JobScheduler,
        repos: Repositories,
        calendar: CalendarPort,
        mail: MailPort,
        notifier: NotifierPort,
        clock: Clock,
        tz: ZoneInfo,
    ) -> None:
        super().__init__(scheduler, repos, calendar, notifier, clock, tz)
        self._mail = mail

    def when(self, settings: NotificationSettings) -> tuple[time | None, int | None]:
        return settings.morning_brief_at, None

    async def summary(self) -> str:
        local_now = self._clock.now().astimezone(self._tz)
        start = datetime.combine(local_now.date(), time(0), tzinfo=self._tz)
        end = start + timedelta(days=1)
        events, calendar_error = await self._events(start, end)
        reminders = [
            r
            for r in await self._repos.reminders.find(ReminderStatus.SCHEDULED)
            if start <= r.due_at < end
        ]
        tasks = await self._repos.tasks.find(Horizon.WEEK, done=False)
        pending = await self._repos.proposals.find(ProposalStatus.PENDING)
        try:
            unread: int | None = len(
                await asyncio.wait_for(
                    self._mail.search(UNREAD_PRIMARY, UNREAD_COUNTED), CALENDAR_SECONDS
                )
            )
        except Exception:  # e.g. Google signed out: leave mail out
            log.warning("morning brief without mail", exc_info=True)
            unread = None

        today = []
        if events:
            today.append(_plural(len(events), "event") + self._first(events))
        if reminders:
            today.append(_plural(len(reminders), "reminder"))
        parts = [
            "Today: " + ", ".join(today) + "."
            if today
            else ("Today is clear." if calendar_error is None else "No reminders today.")
        ]
        if unread:
            count = f"{UNREAD_COUNTED}+" if unread >= UNREAD_COUNTED else str(unread)
            parts.append(f"{count} unread email{'' if unread == 1 else 's'}.")
        parts.append(
            f"{_plural(len(tasks), 'task')} left this week."
            if tasks
            else "No tasks left this week."
        )
        if pending:
            parts.append(f"{_plural(len(pending), 'card')} waiting for your approval.")
        return " ".join(parts)


@dataclass(frozen=True)
class WeekReview:
    since: datetime
    done_tasks: list[Task]
    open_tasks: list[Task]
    overdue_tasks: list[Task]
    reminders_sent: int
    actions_approved: int
    events_next_week: int | None  # None: the calendar couldn't be read
    calendar_error: str | None


async def week_review(repos: Repositories, calendar: CalendarPort, clock: Clock) -> WeekReview:
    """The last 7 days, looking back (the Week page's review card and the weekly push)."""
    now = clock.now()
    since = now - timedelta(days=7)
    done = [
        t
        for t in await repos.tasks.find(None, done=True)
        if t.done_at is not None and t.done_at >= since
    ]
    open_week = await repos.tasks.find(Horizon.WEEK, done=False)
    overdue = [
        t
        for t in await repos.tasks.find(None, done=False)
        if t.due_at is not None and t.due_at < now
    ]
    sent = [r for r in await repos.reminders.find(ReminderStatus.SENT) if since <= r.due_at <= now]
    approved = [
        p
        for p in await repos.proposals.find(ProposalStatus.EXECUTED)
        if p.decided_at is not None and p.decided_at >= since
    ]
    try:
        events: int | None = len(
            await asyncio.wait_for(
                calendar.list_events(now, now + timedelta(days=7)), CALENDAR_SECONDS
            )
        )
        error = None
    except Exception as exc:  # e.g. Google signed out: the rest of the review still counts
        events, error = None, str(exc) or exc.__class__.__name__
    return WeekReview(
        since=since,
        done_tasks=sorted(done, key=lambda t: t.done_at or now, reverse=True),
        open_tasks=open_week,
        overdue_tasks=sorted(overdue, key=lambda t: t.due_at or now),
        reminders_sent=len(sent),
        actions_approved=len(approved),
        events_next_week=events,
        calendar_error=error,
    )


def review_text(review: WeekReview) -> str:
    done = (
        _plural(len(review.done_tasks), "task") + " done"
        if review.done_tasks
        else "no tasks ticked off"
    )
    looking_back = [done]
    if review.reminders_sent:
        looking_back.append(_plural(review.reminders_sent, "reminder") + " sent")
    if review.actions_approved:
        looking_back.append(_plural(review.actions_approved, "action") + " approved")
    parts = ["Last 7 days: " + ", ".join(looking_back) + "."]
    if review.open_tasks or review.overdue_tasks:
        overdue = f" ({len(review.overdue_tasks)} overdue)" if review.overdue_tasks else ""
        parts.append(f"Still open: {_plural(len(review.open_tasks), 'task')} this week{overdue}.")
    else:
        parts.append("Nothing left open this week.")
    if review.events_next_week is not None:
        parts.append(f"Next 7 days: {_plural(review.events_next_week, 'event')}.")
    return " ".join(parts)


class WeeklyReview(_ScheduledPush):
    """Once a week, looking back: what got done and what's still open. Opens the Week page,
    which shows the same review in full."""

    kind, title, url, tag = REVIEW, "Weekly review", "/week", "review"

    def when(self, settings: NotificationSettings) -> tuple[time | None, int | None]:
        return settings.weekly_review_at, settings.weekly_review_day

    async def summary(self) -> str:
        return review_text(await week_review(self._repos, self._calendar, self._clock))
