# Stand-in for Workstream B - not part of the Part C deliverable
"""GET /api/today's daily brief: today's events, free time left, newest unread mail."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from helpmate.api.routes import organize
from helpmate.domain.models import CalendarEvent, EmailSummary, new_id

TZ = ZoneInfo("America/Toronto")


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=TZ)  # conftest's clock: Mon Oct 5 12:00


def mail(subject: str, hours_ago: int, unread: bool = True) -> EmailSummary:
    return EmailSummary(
        id=new_id(),
        sender="Sam <sam@example.com>",
        subject=subject,
        snippet="",
        received_at=at(5, 12) - timedelta(hours=hours_ago),
        unread=unread,
    )


async def test_brief_has_todays_events_the_free_time_left_and_unread_mail(client, container):
    container.calendar.events.extend(
        [
            CalendarEvent(id="e1", title="Standup", start=at(5, 9), end=at(5, 9, 30)),
            CalendarEvent(id="e2", title="Lab", start=at(5, 13), end=at(5, 15)),
            CalendarEvent(id="e3", title="Thanksgiving", start=at(5, 0), end=at(6, 0)),
            CalendarEvent(id="e4", title="Tomorrow", start=at(6, 10), end=at(6, 11)),
        ]
    )
    container.mail.inbox.extend(
        [mail(f"unread {i}", hours_ago=i) for i in range(1, 8)] + [mail("read", 0, unread=False)]
    )
    brief = (await client.get("/api/today")).json()

    assert [e["title"] for e in brief["events"]] == ["Thanksgiving", "Standup", "Lab"]
    # from now (noon) to 18:00, around the lab; the all-day event doesn't count as busy
    assert [(s["start"][11:16], s["end"][11:16]) for s in brief["free_slots"]] == [
        ("12:00", "13:00"),
        ("15:00", "18:00"),
    ]
    assert [m["subject"] for m in brief["unread"]] == [f"unread {i}" for i in range(1, 6)]
    assert brief["calendar_error"] is None and brief["mail_error"] is None


async def test_a_failing_connector_only_empties_its_own_section(client, container):
    async def expired(*_args):
        raise RuntimeError("Google's sign-in expired. Run google_auth.py")

    container.calendar.list_events = expired
    container.mail.inbox.append(mail("still here", 1))
    brief = (await client.get("/api/today")).json()
    assert brief["calendar_error"] == "Google's sign-in expired. Run google_auth.py"
    assert brief["events"] == [] and brief["free_slots"] == []
    assert [m["subject"] for m in brief["unread"]] == ["still here"]
    assert brief["mail_error"] is None


async def test_a_slow_connector_times_out(client, container, monkeypatch):
    monkeypatch.setattr(organize, "BRIEF_TIMEOUT_SECONDS", 0.05)

    async def slow(*_args):
        await asyncio.sleep(1)
        return []

    container.mail.search = slow
    brief = (await client.get("/api/today")).json()
    assert brief["mail_error"] == "Google didn't answer in time. Try again in a moment."
    assert brief["calendar_error"] is None
