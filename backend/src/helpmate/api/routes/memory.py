"""Memory review queue and 'everything HelpMate remembers' (view, delete, export)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from helpmate.api.deps import ContainerDep, current_user
from helpmate.api.schemas.bodies import ExportOut, SuggestionDecisionIn
from helpmate.domain.models import (
    MemoryFact,
    MemorySuggestion,
    SuggestionStatus,
    new_id,
)

router = APIRouter(tags=["memory"], dependencies=[Depends(current_user)])


@router.get("/memory/suggestions", response_model=list[MemorySuggestion])
async def list_suggestions(
    container: ContainerDep, status: SuggestionStatus | None = SuggestionStatus.PENDING
) -> list[MemorySuggestion]:
    return await container.repos.memory.find_suggestions(status)


@router.post("/memory/suggestions/{suggestion_id}/decision", response_model=MemorySuggestion)
async def decide_suggestion(
    suggestion_id: str, body: SuggestionDecisionIn, container: ContainerDep
) -> MemorySuggestion:
    suggestion = await container.repos.memory.get_suggestion(suggestion_id)
    if suggestion is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "suggestion not found")
    if suggestion.status != SuggestionStatus.PENDING:
        raise HTTPException(status.HTTP_409_CONFLICT, f"suggestion is already {suggestion.status}")
    if body.decision == "approve":
        suggestion.status = SuggestionStatus.APPROVED
        await container.repos.memory.add_fact(
            MemoryFact(
                id=new_id(),
                text=suggestion.text,
                source=suggestion.source,
                created_at=container.clock.now(),
            )
        )
    else:
        suggestion.status = SuggestionStatus.REJECTED
    await container.repos.memory.update_suggestion(suggestion)
    return suggestion


@router.get("/memory/facts", response_model=list[MemoryFact])
async def list_facts(container: ContainerDep) -> list[MemoryFact]:
    return await container.repos.memory.find_facts()


@router.delete("/memory/facts/{fact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_fact(fact_id: str, container: ContainerDep) -> None:
    if not await container.repos.memory.delete_fact(fact_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "fact not found")


@router.get("/export", response_model=ExportOut)
async def export_everything(container: ContainerDep) -> ExportOut:
    repos = container.repos
    folders = await repos.folders.find()
    sessions = await repos.chat.find_sessions()
    items = [item for f in folders for item in await repos.folders.find_items(f.id)]
    messages = [m for s in sessions for m in await repos.chat.find_messages(s.id)]
    return ExportOut(
        exported_at=container.clock.now(),
        folders=folders,
        items=items,
        tasks=await repos.tasks.find(),
        reminders=await repos.reminders.find(),
        facts=await repos.memory.find_facts(),
        suggestions=await repos.memory.find_suggestions(),
        proposals=await repos.proposals.find(),
        chat_sessions=sessions,
        chat_messages=messages,
        audit=await repos.audit.find(limit=10_000),
    )
