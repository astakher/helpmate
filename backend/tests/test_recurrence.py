# Stand-in for Workstream B - not part of the Part C deliverable
"""Recurring reminders follow the owner's wall clock, including across the Nov 1, 2026 DST change
(the spec's "recurring reminders across the daylight-saving change on November 1")."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from helpmate.adapters.clock import FakeClock
from helpmate.adapters.fakes.dev_scheduler import DevScheduler
from helpmate.adapters.fakes.log_notifier import LogNotifier
from helpmate.adapters.fakes.memory_repos import InMemoryRepositories
from helpmate.domain.models import Reminder, ReminderStatus
from helpmate.worker.recurrence import InvalidRecurrence, next_occurrence

TZ = ZoneInfo("America/Toronto")


def local(dt: datetime) -> str:
    return dt.astimezone(TZ).strftime("%a %Y-%m-%d %H:%M %Z")


def test_weekly_keeps_0800_local_across_the_fall_back_change():
    monday = datetime(2026, 10, 26, 8, 0, tzinfo=TZ)  # EDT
    after = next_occurrence("FREQ=WEEKLY;BYDAY=MO", monday, TZ)
    assert local(after) == "Mon 2026-11-02 08:00 EST"
    assert (monday.astimezone(UTC).hour, after.hour) == (
        12,
        13,
    )  # UTC moved, the owner's time didn't
    assert after.tzinfo == UTC  # stored as UTC


def test_daily_across_the_change_and_weekdays_skip_the_weekend():
    saturday = datetime(2026, 10, 31, 7, 0, tzinfo=TZ)
    assert local(next_occurrence("FREQ=DAILY", saturday, TZ)) == "Sun 2026-11-01 07:00 EST"
    friday = datetime(2026, 10, 30, 6, 45, tzinfo=TZ)
    weekdays = "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"
    assert local(next_occurrence(weekdays, friday, TZ)) == "Mon 2026-11-02 06:45 EST"


def test_spring_forward_gap_fires_at_0330_that_day():
    before = datetime(2027, 3, 13, 2, 30, tzinfo=TZ)
    assert local(next_occurrence("FREQ=DAILY", before, TZ)) == "Sun 2027-03-14 03:30 EDT"


def test_missed_occurrences_are_skipped_not_fired_in_a_burst():
    monday = datetime(2026, 10, 5, 8, 0, tzinfo=TZ)
    three_weeks_later = datetime(2026, 10, 25, 12, 0, tzinfo=TZ)
    following = next_occurrence("FREQ=WEEKLY;BYDAY=MO", monday, TZ, after=three_weeks_later)
    assert local(following) == "Mon 2026-10-26 08:00 EDT"


def test_count_runs_out_and_bad_rules_are_reported():
    first = datetime(2026, 10, 5, 8, 0, tzinfo=TZ)
    second = next_occurrence("FREQ=DAILY;COUNT=2", first, TZ)
    assert next_occurrence("FREQ=DAILY;COUNT=2", first, TZ, after=second) is None
    with pytest.raises(InvalidRecurrence):
        next_occurrence("EVERY MONDAY", first, TZ)


async def test_scheduler_fires_a_weekly_reminder_on_both_sides_of_nov_1():
    """End to end with the fake clock: the same reminder fires at 08:00 local each Monday."""
    repos, notifier = InMemoryRepositories(), LogNotifier()
    clock = FakeClock(datetime(2026, 10, 26, 7, 59, tzinfo=TZ))
    scheduler = DevScheduler(repos, notifier, clock, tz=TZ)
    await repos.reminders.add(
        Reminder(
            id="r1",
            text="plan my week",
            due_at=datetime(2026, 10, 26, 8, 0, tzinfo=TZ).astimezone(UTC),
            recurrence="FREQ=WEEKLY;BYDAY=MO",
            created_at=clock.now(),
        )
    )

    assert await scheduler.tick() == 0  # 07:59, not yet
    clock.advance(minutes=1, seconds=5)
    assert await scheduler.tick() == 1
    reminder = await repos.reminders.get("r1")
    assert reminder.status == ReminderStatus.SCHEDULED  # still recurring
    assert local(reminder.due_at) == "Mon 2026-11-02 08:00 EST"

    clock.advance(days=7)  # 7 x 24 h later is only 07:00 local: the clocks went back an hour
    assert await scheduler.tick() == 0  # so the 08:00 EST occurrence isn't due yet
    clock.advance(hours=1)  # Mon Nov 2, 08:00 local (EST)
    assert await scheduler.tick() == 1
    assert [n.body for n in notifier.sent] == ["plan my week", "plan my week"]
    deliveries = await repos.deliveries.find()
    assert sorted(local(d.due_at) for d in deliveries) == [
        "Mon 2026-10-26 08:00 EDT",
        "Mon 2026-11-02 08:00 EST",
    ]
    assert local((await repos.reminders.get("r1")).due_at) == "Mon 2026-11-09 08:00 EST"


async def test_one_off_and_unreadable_rules_fire_once():
    repos, notifier = InMemoryRepositories(), LogNotifier()
    clock = FakeClock(datetime(2026, 10, 5, 12, 0, tzinfo=TZ))
    scheduler = DevScheduler(repos, notifier, clock, tz=TZ)
    for rid, rule in (("once", None), ("bad", "EVERY MONDAY")):
        await repos.reminders.add(
            Reminder(
                id=rid,
                text=rid,
                due_at=clock.now() - timedelta(minutes=1),
                recurrence=rule,
                created_at=clock.now(),
            )
        )
    assert await scheduler.tick() == 2
    statuses = {r.id: r.status for r in await repos.reminders.find()}
    assert statuses == {"once": ReminderStatus.SENT, "bad": ReminderStatus.SENT}
