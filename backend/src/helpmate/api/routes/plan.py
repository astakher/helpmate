# Stand-in for Workstream B - not part of the Part C deliverable
"""The week plan: the next 7 days at a glance, and "find time" for a task.

GET /api/week lists each day's events, free time (inside the owner's day hours), reminders and
tasks due, plus this week's tasks without a date. POST /api/week/schedule-task finds the first
free slot of the requested length and proposes a calendar event for it: an approval card like any
other agent write, so nothing lands in the calendar until the owner approves it.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, status

from helpmate.agent.free_time import free_slots
from helpmate.api.deps import ContainerDep, current_user
from helpmate.api.schemas.bodies import DayPlan, ScheduleTaskIn, TimeRange, WeekOut
from helpmate.domain.models import (
    CalendarEvent,
    Horizon,
    Proposal,
    ReminderStatus,
    ToolCall,
    new_id,
)

router = APIRouter(prefix="/week", tags=["plan"], dependencies=[Depends(current_user)])

DAYS = 7
SLOT_MINUTES = 30
CALENDAR_TIMEOUT_SECONDS = 8.0


@router.get("", response_model=WeekOut)
async def week(container: ContainerDep) -> WeekOut:
    tz = container.settings.tz
    now = container.clock.now()
    today = now.astimezone(tz).date()
    start = datetime.combine(today, time(0), tzinfo=tz)
    end = datetime.combine(today + timedelta(days=DAYS), time(0), tzinfo=tz)
    events, error = await _events(container, start, end)
    hours = (container.settings.day_start_hour, container.settings.day_end_hour)
    reminders = await container.repos.reminders.find(ReminderStatus.SCHEDULED)
    tasks = await container.repos.tasks.find(done=False)

    days = []
    for offset in range(DAYS):
        day_start = datetime.combine(today + timedelta(days=offset), time(0), tzinfo=tz)
        day_end = day_start + timedelta(days=1)
        day_events = [e for e in events if e.start < day_end and e.end > day_start]
        slots = (
            free_slots(day_events, max(day_start, now), day_end, SLOT_MINUTES, tz, hours)
            if error is None
            else []
        )
        days.append(
            DayPlan(
                date=day_start.date().isoformat(),
                events=day_events,
                free_slots=[TimeRange(start=a, end=b) for a, b in slots],
                reminders=[r for r in reminders if day_start <= r.due_at < day_end],
                tasks_due=[t for t in tasks if t.due_at and day_start <= t.due_at < day_end],
            )
        )
    # a task counts as fitted in once an event this week has its title ("Find an hour" names the
    # event after the task, and the owner may have booked one by hand)
    booked = {" ".join(e.title.lower().split()) for e in events}
    unscheduled = [
        t
        for t in tasks
        if t.horizon == Horizon.WEEK
        and t.due_at is None
        and " ".join(t.title.lower().split()) not in booked
    ]
    return WeekOut(
        timezone=container.settings.timezone,
        days=days,
        unscheduled=unscheduled,
        calendar_error=error,
    )


@router.post("/schedule-task", response_model=Proposal, status_code=status.HTTP_201_CREATED)
async def schedule_task(body: ScheduleTaskIn, container: ContainerDep) -> Proposal:
    """Propose a calendar event for the task in the first free slot that fits (approval card)."""
    task = await container.repos.tasks.get(body.task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    tz = container.settings.tz
    now = container.clock.now()
    end = datetime.combine(now.astimezone(tz).date() + timedelta(days=DAYS), time(0), tzinfo=tz)
    events, error = await _events(container, now, end)
    if error is not None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"Couldn't read your calendar: {error}"
        )
    hours = (container.settings.day_start_hour, container.settings.day_end_hour)
    slots = free_slots(events, now, end, body.minutes, tz, hours)
    if not slots:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"No free {body.minutes} minutes in the next {DAYS} days "
            f"between {hours[0]:02d}:00 and {hours[1]:02d}:00.",
        )
    start = slots[0][0]
    outcome = await container.policy.handle_call(
        ToolCall(
            id=new_id(),
            name="create_event",
            arguments={
                "title": task.title,
                "start": start.isoformat(),
                "end": (start + timedelta(minutes=body.minutes)).isoformat(),
                "description": "Time for a task from HelpMate's week plan.",
            },
        )
    )
    if outcome.proposal is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, outcome.summary)
    return outcome.proposal


async def _events(
    container: ContainerDep, start: datetime, end: datetime
) -> tuple[list[CalendarEvent], str | None]:
    try:
        events = await asyncio.wait_for(
            container.calendar.list_events(start, end), CALENDAR_TIMEOUT_SECONDS
        )
    except TimeoutError:
        return [], "Google didn't answer in time. Try again in a moment."
    except Exception as exc:  # e.g. GoogleNotConnected: its message says how to fix it
        return [], str(exc) or exc.__class__.__name__
    return events, None
