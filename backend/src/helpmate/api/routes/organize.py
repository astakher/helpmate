"""Folders, items, tasks, reminders and the Today board.

These are the owner's own direct edits from the UI, so they need no approval. Only
agent-initiated writes go through proposals.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

from fastapi import APIRouter, Depends, HTTPException, status

from helpmate.api.deps import ContainerDep, current_user
from helpmate.api.schemas.bodies import (
    CreateFolderIn,
    CreateItemIn,
    CreateTaskIn,
    PatchTaskIn,
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


@router.get("/today", response_model=TodayOut)
async def today(container: ContainerDep) -> TodayOut:
    tz = container.settings.tz
    now_local = container.clock.now().astimezone(tz)
    start = datetime.combine(now_local.date(), time.min, tzinfo=tz)
    end = datetime.combine(now_local.date() + timedelta(days=1), time.min, tzinfo=tz)
    reminders = [
        r
        for r in await container.repos.reminders.find(ReminderStatus.SCHEDULED)
        if start <= r.due_at < end
    ]
    return TodayOut(
        date=now_local.date().isoformat(),
        timezone=container.settings.timezone,
        reminders=reminders,
        tasks=await container.repos.tasks.find(Horizon.WEEK, done=False),
        pending_proposals=await container.repos.proposals.find(ProposalStatus.PENDING),
    )


async def _require_folder(container: Container, folder_id: str) -> Folder:
    folder = await container.repos.folders.get(folder_id)
    if folder is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "folder not found")
    return folder
