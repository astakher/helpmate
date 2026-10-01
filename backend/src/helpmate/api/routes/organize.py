"""Folders, items, tasks, reminders and the Today board.

These are the owner's own direct edits from the UI, so they need no approval. Only
agent-initiated writes go through proposals.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from datetime import UTC, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, status

from helpmate.agent.free_time import free_slots
from helpmate.api.deps import ContainerDep, current_user
from helpmate.api.schemas.bodies import (
    CreateFolderIn,
    CreateItemIn,
    CreateTaskIn,
    PatchTaskIn,
    TimeRange,
    TodayOut,
)
from helpmate.container import Container
from helpmate.domain.models import (
    Folder,
    FolderKind,
    Horizon,
    Item,
    ProposalStatus,
    Reminder,
    ReminderStatus,
    Task,
    new_id,
)

router = APIRouter(tags=["organize"], dependencies=[Depends(current_user)])


# --- folders & items ---


@router.get("/folders", response_model=list[Folder])
async def list_folders(container: ContainerDep) -> list[Folder]:
    return await container.repos.folders.find()


@router.post("/folders", response_model=Folder, status_code=status.HTTP_201_CREATED)
async def create_folder(body: CreateFolderIn, container: ContainerDep) -> Folder:
    folder = Folder(
        id=new_id(),
        name=body.name,
        kind=FolderKind.CUSTOM,
        fields=body.fields,
        created_at=container.clock.now(),
    )
    await container.repos.folders.add(folder)
    return folder


@router.get("/folders/{folder_id}/items", response_model=list[Item])
async def list_items(folder_id: str, container: ContainerDep) -> list[Item]:
    await _require_folder(container, folder_id)
    return await container.repos.folders.find_items(folder_id)


@router.post("/folders/{folder_id}/items", response_model=Item, status_code=status.HTTP_201_CREATED)
async def create_item(folder_id: str, body: CreateItemIn, container: ContainerDep) -> Item:
    folder = await _require_folder(container, folder_id)
    unknown = set(body.fields) - {f.key for f in folder.fields}
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"unknown fields: {sorted(unknown)}"
        )
    item = Item(
        id=new_id(),
        folder_id=folder_id,
        title=body.title,
        fields=body.fields,
        source="manual",
        created_at=container.clock.now(),
    )
    await container.repos.folders.add_item(item)
    return item


# --- tasks ---


@router.get("/tasks", response_model=list[Task])
async def list_tasks(
    container: ContainerDep, horizon: Horizon | None = None, done: bool | None = None
) -> list[Task]:
    return await container.repos.tasks.find(horizon, done)


@router.post("/tasks", response_model=Task, status_code=status.HTTP_201_CREATED)
async def create_task(body: CreateTaskIn, container: ContainerDep) -> Task:
    task = Task(
        id=new_id(),
        title=body.title,
        horizon=body.horizon,
        folder_id=body.folder_id,
        due_at=body.due_at.astimezone(UTC) if body.due_at else None,
        created_at=container.clock.now(),
    )
    await container.repos.tasks.add(task)
    return task


@router.patch("/tasks/{task_id}", response_model=Task)
async def update_task(task_id: str, body: PatchTaskIn, container: ContainerDep) -> Task:
    task = await container.repos.tasks.get(task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    changes = body.model_dump(exclude_unset=True)
    if changes.get("due_at") is not None:
        changes["due_at"] = changes["due_at"].astimezone(UTC)
    updated = task.model_copy(update=changes)
    await container.repos.tasks.update(updated)
    return updated


# --- reminders ---


@router.get("/reminders", response_model=list[Reminder])
async def list_reminders(
    container: ContainerDep, status: ReminderStatus | None = None
) -> list[Reminder]:
    return await container.repos.reminders.find(status)


@router.post("/reminders/{reminder_id}/cancel", response_model=Reminder)
async def cancel_reminder(reminder_id: str, container: ContainerDep) -> Reminder:
    await container.scheduler.cancel(reminder_id)
    reminder = await container.repos.reminders.get(reminder_id)
    if reminder is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "reminder not found")
    return reminder


# --- today ---


BRIEF_TIMEOUT_SECONDS = 8.0  # a slow Google answer mustn't hold up the whole Today page
FREE_SLOT_MINUTES = 30
UNREAD_SHOWN = 5


@router.get("/today", response_model=TodayOut)
async def today(container: ContainerDep) -> TodayOut:
    """The Today board and daily brief: today's reminders and events, free time left, newest
    unread mail, this week's tasks and what's waiting for approval."""
    tz = container.settings.tz
    now = container.clock.now()
    now_local = now.astimezone(tz)
    start = datetime.combine(now_local.date(), time.min, tzinfo=tz)
    end = datetime.combine(now_local.date() + timedelta(days=1), time.min, tzinfo=tz)
    reminders = [
        r
        for r in await container.repos.reminders.find(ReminderStatus.SCHEDULED)
        if start <= r.due_at < end
    ]
    (events, calendar_error), (unread, mail_error) = await asyncio.gather(
        _section(container.calendar.list_events(start, end)),
        _section(container.mail.search("in:inbox is:unread", UNREAD_SHOWN)),
    )
    hours = (container.settings.day_start_hour, container.settings.day_end_hour)
    free = (
        free_slots(events or [], max(start, now), end, FREE_SLOT_MINUTES, tz, hours)
        if calendar_error is None
        else []
    )
    return TodayOut(
        date=now_local.date().isoformat(),
        timezone=container.settings.timezone,
        reminders=reminders,
        tasks=await container.repos.tasks.find(Horizon.WEEK, done=False),
        pending_proposals=await container.repos.proposals.find(ProposalStatus.PENDING),
        events=events or [],
        free_slots=[TimeRange(start=a, end=b) for a, b in free],
        unread=(unread or [])[:UNREAD_SHOWN],
        calendar_error=calendar_error,
        mail_error=mail_error,
    )


async def _section[T](read: Awaitable[T]) -> tuple[T | None, str | None]:
    """One connector's part of the brief: its data, or why it couldn't be read."""
    try:
        return await asyncio.wait_for(read, BRIEF_TIMEOUT_SECONDS), None
    except TimeoutError:
        return None, "Google didn't answer in time. Try again in a moment."
    except Exception as exc:  # e.g. GoogleNotConnected: its message says how to fix it
        return None, str(exc) or exc.__class__.__name__


async def _require_folder(container: Container, folder_id: str) -> Folder:
    folder = await container.repos.folders.get(folder_id)
    if folder is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "folder not found")
    return folder
