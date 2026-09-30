"""QuietHoursNotifier (Part C): quiet hours, max per hour and private previews."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from helpmate.adapters.clock import FakeClock
from helpmate.adapters.fakes.log_notifier import LogNotifier
from helpmate.adapters.fakes.memory_repos import InMemorySettingsRepo
from helpmate.adapters.quiet_hours import QuietHoursNotifier, quiet_hours_end
from helpmate.domain.models import (
    Notification,
    NotificationKind,
    NotificationSettings,
    QuietHours,
)

TZ = ZoneInfo("America/Toronto")
NIGHT = QuietHours(start=time(22, 0), end=time(7, 0))


def note(i: int = 1, urgent: bool = False, kind=NotificationKind.BRIEF) -> Notification:
    return Notification(id=f"n{i}", kind=kind, title="Morning brief", body="3 tasks", urgent=urgent)


async def setup(now: datetime, **prefs):
    settings = InMemorySettingsRepo()
    await settings.put_notification_settings(NotificationSettings(**prefs))
    inner, clock = LogNotifier(), FakeClock(now)
    return QuietHoursNotifier(inner, settings, clock), inner, clock


async def test_quiet_hours_hold_non_urgent_until_they_end_but_urgent_goes_through():
    notifier, inner, clock = await setup(
        datetime(2026, 10, 5, 23, 30, tzinfo=TZ), quiet_hours=NIGHT
    )

    held = await notifier.notify(note(1))
    assert held.deferred and held.delivered == 0 and held.detail == "held until 07:00"
    reminder = await notifier.notify(note(2, urgent=True, kind=NotificationKind.REMINDER))
    assert not reminder.deferred and [n.id for n in inner.sent] == ["n2"]

    assert await notifier.flush() == 0  # still night
    clock.advance(hours=7, minutes=31)  # 07:01
    assert await notifier.flush() == 1
    assert [n.id for n in inner.sent] == ["n2", "n1"] and notifier.held == []
    await notifier.aclose()


async def test_max_per_hour_holds_the_extra_ones_until_the_hour_frees_up():
    notifier, inner, clock = await setup(datetime(2026, 10, 5, 12, 0, tzinfo=TZ), max_per_hour=2)
    for i in range(3):
        await notifier.notify(note(i))
        clock.advance(minutes=10)
    assert [n.id for n in inner.sent] == ["n0", "n1"] and [n.id for n in notifier.held] == ["n2"]
    urgent = await notifier.notify(note(9, urgent=True))  # the owner's reminders never wait
    assert not urgent.deferred

    clock.advance(minutes=31)  # 12:61 -> n0 is over an hour old
    assert await notifier.flush() == 1 and inner.sent[-1].id == "n2"
    await notifier.aclose()


async def test_private_previews_hide_the_text():
    notifier, inner, _ = await setup(datetime(2026, 10, 5, 12, 0, tzinfo=TZ), private_previews=True)
    await notifier.notify(note(1, urgent=True, kind=NotificationKind.REMINDER))
    [sent] = inner.sent
    assert (sent.title, sent.body) == ("HelpMate", "You have a reminder") and sent.id == "n1"


def test_quiet_window_wraps_midnight_and_ignores_daytime():
    prefs = NotificationSettings(quiet_hours=NIGHT)
    at = lambda h, m=0: datetime(2026, 10, 5, h, m, tzinfo=TZ)  # noqa: E731
    assert quiet_hours_end(at(23), prefs) == datetime(2026, 10, 6, 7, 0, tzinfo=TZ)
    assert quiet_hours_end(at(3), prefs) == datetime(2026, 10, 5, 7, 0, tzinfo=TZ)
    assert quiet_hours_end(at(7), prefs) is None and quiet_hours_end(at(12), prefs) is None
    daytime = NotificationSettings(quiet_hours=QuietHours(start=time(13), end=time(14)))
    assert quiet_hours_end(at(13, 30), daytime) == datetime(2026, 10, 5, 14, 0, tzinfo=TZ)


def test_name_reports_both_layers():
    notifier = QuietHoursNotifier(
        LogNotifier(), InMemorySettingsRepo(), FakeClock(datetime.now(TZ))
    )
    assert notifier.name == "log+quiet-hours" and notifier.is_fake
