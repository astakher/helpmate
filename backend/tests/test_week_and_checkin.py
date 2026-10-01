# Stand-in for Workstream B - not part of the Part C deliverable
"""The week plan (GET /api/week, POST /api/week/schedule-task) and the evening check-in job."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from helpmate.adapters.clock import FakeClock
from helpmate.adapters.fakes.connectors import FakeCalendar
from helpmate.adapters.fakes.memory_repos import InMemoryRepositories
from helpmate.domain.models import (
    CalendarEvent,
    DeliveryResult,
    Horizon,
    Notification,
    NotificationSettings,
    ProposalStatus,
    Reminder,
    Task,
    new_id,
)
from helpmate.worker.checkin import EveningCheckIn
from helpmate.worker.jobs import InMemoryJobStore
from helpmate.worker.scheduler import JobScheduler

TZ = ZoneInfo("America/Toronto")


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=TZ)  # conftest's clock: Mon Oct 5 12:00


def task(title: str, due: datetime | None = None, horizon: Horizon = Horizon.WEEK) -> Task:
    return Task(id=new_id(), title=title, horizon=horizon, due_at=due, created_at=at(5, 9))


# --- the week plan ----------------------------------------------------------------------------


async def test_week_lists_seven_days_with_events_free_time_reminders_and_tasks(client, container):
    container.calendar.events.extend(
        [
            CalendarEvent(id="e1", title="Lab", start=at(5, 13), end=at(5, 15)),
            CalendarEvent(id="e2", title="Standup", start=at(6, 9), end=at(6, 10)),
        ]
    )
    await container.repos.reminders.add(
        Reminder(id="r1", text="pay rent", due_at=at(7, 9), created_at=at(5, 9))
    )
    for t in (
        task("essay draft", at(8, 17)),
        task("read ch. 3"),
        task("someday", None, Horizon.SOMEDAY),
    ):
        await container.repos.tasks.add(t)

    week = (await client.get("/api/week")).json()
    days = week["days"]
    assert [d["date"] for d in days] == [f"2026-10-{d:02d}" for d in range(5, 12)]
    assert [e["title"] for e in days[0]["events"]] == ["Lab"]
    # today starts from now (noon) and goes around the lab; tomorrow starts after standup
    assert [(s["start"][11:16], s["end"][11:16]) for s in days[0]["free_slots"]] == [
        ("12:00", "13:00"),
        ("15:00", "18:00"),
    ]
    assert days[1]["free_slots"][0]["start"][11:16] == "10:00"
    assert [r["text"] for r in days[2]["reminders"]] == ["pay rent"]
    assert [t["title"] for t in days[3]["tasks_due"]] == ["essay draft"]
    assert [t["title"] for t in week["unscheduled"]] == ["read ch. 3"]  # week tasks without a date


async def test_find_time_proposes_an_event_in_the_first_free_hour(client, container):
    container.calendar.events.append(
        CalendarEvent(id="e1", title="Lab", start=at(5, 12, 30), end=at(5, 15))
    )
    t = task("read ch. 3")
    await container.repos.tasks.add(t)
    response = await client.post("/api/week/schedule-task", json={"task_id": t.id, "minutes": 60})
    assert response.status_code == 201
    card = response.json()
    assert card["tool"] == "create_event" and card["status"] == ProposalStatus.PENDING
    assert card["title"] == "Event: read ch. 3"
    assert card["args"]["start"].startswith("2026-10-05T15:00")  # noon-12:30 is too short
    assert card["warnings"] == []
    assert len(container.calendar.events) == 1  # nothing added before approval


async def test_find_time_explains_when_nothing_fits(client, container):
    for day in range(5, 12):  # a fully booked week
        container.calendar.events.append(
            CalendarEvent(id=f"busy{day}", title="Busy", start=at(day, 8), end=at(day, 19))
        )
    t = task("read ch. 3")
    await container.repos.tasks.add(t)
    response = await client.post("/api/week/schedule-task", json={"task_id": t.id})
    assert response.status_code == 409 and "No free 60 minutes" in response.json()["detail"]
    missing = await client.post("/api/week/schedule-task", json={"task_id": "nope"})
    assert missing.status_code == 404


# --- the evening check-in ---------------------------------------------------------------------


class Phone:
    name, is_fake = "phone", True

    def __init__(self) -> None:
        self.shown: list[Notification] = []

    async def notify(self, notification: Notification) -> DeliveryResult:
        self.shown.append(notification)
        return DeliveryResult(notification_id=notification.id, delivered=1)


async def _checkin(clock: FakeClock, checkin_at: time | None = time(20, 0)):
    repos = InMemoryRepositories()
    await repos.settings.put_notification_settings(NotificationSettings(checkin_at=checkin_at))
    phone, calendar = Phone(), FakeCalendar()
    jobs = JobScheduler(InMemoryJobStore(), repos, phone, clock, TZ)
    EveningCheckIn(jobs, repos, calendar, phone, clock, TZ).install()
    return jobs, repos, calendar, phone


async def test_the_check_in_arrives_at_the_chosen_time_and_sums_up_tomorrow():
    clock = FakeClock(at(5, 12))
    jobs, repos, calendar, phone = await _checkin(clock)
    await repos.tasks.add(task("read ch. 3"))
    await repos.tasks.add(task("essay"))
    await repos.reminders.add(Reminder(id="r", text="rent", due_at=at(6, 9), created_at=at(5, 9)))
    calendar.events += [
        CalendarEvent(id="a", title="Standup", start=at(6, 9, 30), end=at(6, 10)),
        CalendarEvent(id="b", title="Lab", start=at(6, 13), end=at(6, 15)),
    ]
    await jobs.tick()
    assert phone.shown == []  # queued for 20:00
    assert await jobs.store.next_run_at() == at(5, 20)
    clock.advance(hours=8)
    await jobs.tick()
    [checkin] = phone.shown
    assert (checkin.title, checkin.url) == ("Evening check-in", "/week")
    assert (
        checkin.body == "2 tasks left this week. Tomorrow: 2 events (first at 09:30), 1 reminder."
    )
    assert await jobs.store.next_run_at() == at(6, 20)  # and tomorrow's is queued


async def test_turning_it_off_or_moving_it_stops_the_old_job():
    clock = FakeClock(at(5, 12))
    jobs, repos, _, phone = await _checkin(clock)
    await jobs.tick()  # 20:00 queued
    await repos.settings.put_notification_settings(NotificationSettings(checkin_at=time(21, 0)))
    clock.advance(hours=8)
    await jobs.tick()
    assert phone.shown == []  # the 20:00 job saw the new time
    clock.advance(hours=1)
    await jobs.tick()
    assert len(phone.shown) == 1  # the 21:00 one ran
    await repos.settings.put_notification_settings(NotificationSettings(checkin_at=None))
    clock.advance(days=1)
    await jobs.tick()
    assert len(phone.shown) == 1  # off


async def test_a_check_in_missed_by_hours_is_skipped_and_an_empty_week_says_so():
    clock = FakeClock(at(5, 19, 59))
    jobs, _, _, phone = await _checkin(clock)
    await jobs.tick()
    clock.advance(hours=5)  # the laptop slept through the evening
    await jobs.tick()
    assert phone.shown == []
    clock.advance(hours=20)  # 20:59 the next day, on time
    await jobs.tick()
    assert phone.shown[0].body == "No tasks left this week. Tomorrow is clear."


async def test_a_task_with_an_event_this_week_no_longer_needs_fitting_in(client, container):
    booked, open_ = task("Read ch. 3"), task("essay")
    for t in (booked, open_):
        await container.repos.tasks.add(t)
    container.calendar.events.append(
        CalendarEvent(id="e1", title="read  ch. 3", start=at(6, 10), end=at(6, 11))
    )
    week = (await client.get("/api/week")).json()
    assert [t["title"] for t in week["unscheduled"]] == ["essay"]
