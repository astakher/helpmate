"""Calendar logic on top of CalendarPort.list_events: conflicts and free time.

All-day events (holidays, birthdays, "working from home") are shown when listing but don't make
the owner busy: counting them would block whole days.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from helpmate.domain.models import CalendarEvent

SLOT_STEP = timedelta(minutes=15)  # free slots start on a quarter hour


def is_all_day(event: CalendarEvent, tz: ZoneInfo) -> bool:
    start = event.start.astimezone(tz)
    return start.time() == time(0) and event.end - event.start >= timedelta(days=1)


def conflicts(
    events: list[CalendarEvent], start: datetime, end: datetime, tz: ZoneInfo
) -> list[CalendarEvent]:
    """Timed events that overlap [start, end). Touching end-to-start isn't a conflict."""
    return [e for e in events if e.start < end and e.end > start and not is_all_day(e, tz)]


def free_slots(
    events: list[CalendarEvent],
    start: datetime,
    end: datetime,
    minutes: int,
    tz: ZoneInfo,
    day_hours: tuple[int, int] = (9, 18),
) -> list[tuple[datetime, datetime]]:
    """Free windows at least `minutes` long inside the owner's day hours, within [start, end)."""
    busy = sorted(
        (e.start.astimezone(tz), e.end.astimezone(tz)) for e in events if not is_all_day(e, tz)
    )
    needed = timedelta(minutes=minutes)
    slots: list[tuple[datetime, datetime]] = []
    day: date = start.astimezone(tz).date()
    while (day_start := datetime.combine(day, time(day_hours[0]), tzinfo=tz)) < end:
        cursor = _round_up(max(day_start, start.astimezone(tz)))
        day_end = min(datetime.combine(day, time(day_hours[1]), tzinfo=tz), end.astimezone(tz))
        for busy_start, busy_end in busy:
            if busy_end <= cursor or busy_start >= day_end:
                continue
            if busy_start - cursor >= needed:
                slots.append((cursor, busy_start))
            cursor = max(cursor, _round_up(busy_end))
        if day_end - cursor >= needed:
            slots.append((cursor, day_end))
        day += timedelta(days=1)
    return slots


def _round_up(moment: datetime) -> datetime:
    floor = moment.replace(minute=0, second=0, microsecond=0)
    steps = -(-(moment - floor) // SLOT_STEP)  # ceiling division
    return floor + steps * SLOT_STEP
