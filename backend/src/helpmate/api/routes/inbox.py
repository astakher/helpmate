# Stand-in for Workstream B - not part of the Part C deliverable
"""Inbox triage (agent/triage.py): GET /api/inbox sorts unread mail; POST
/api/inbox/{message_id}/draft-reply drafts a reply as a send_email approval card."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, status

from helpmate.api.deps import ContainerDep, current_user
from helpmate.api.schemas.bodies import InboxOut, TriagedEmail
from helpmate.domain.models import Proposal, ToolCall, new_id

router = APIRouter(prefix="/inbox", tags=["inbox"], dependencies=[Depends(current_user)])

SORT_TIMEOUT_SECONDS = 60.0  # ~0.5 s per email with the local model


@router.get("", response_model=InboxOut)
async def inbox(container: ContainerDep) -> InboxOut:
    try:
        sorted_mail = await asyncio.wait_for(container.triage.sort(), SORT_TIMEOUT_SECONDS)
    except TimeoutError:
        return InboxOut(items=[], error="Sorting took too long. Try again in a moment.")
    except Exception as exc:  # e.g. GoogleNotConnected: its message says how to fix it
        return InboxOut(items=[], error=str(exc) or exc.__class__.__name__)
    return InboxOut(
        items=[
            TriagedEmail(
                email=t.email,
                category=t.category.value,
                reason=t.reason,
                suspicious=t.suspicious,
                sorted_by="model" if t.sorted_by == "model" else "rules",
            )
            for t in sorted_mail
        ]
    )


@router.post(
    "/{message_id}/draft-reply", response_model=Proposal, status_code=status.HTTP_201_CREATED
)
async def draft_reply(message_id: str, container: ContainerDep) -> Proposal:
    """A reply to the sender, written by the local model, as an approval card (nothing is sent
    until the owner approves it, and the card shows the whole text)."""
    try:
        args, _ = await container.triage.reply_args(message_id)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "message not found") from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    outcome = await container.policy.handle_call(
        ToolCall(id=new_id(), name="send_email", arguments=args)
    )
    if outcome.proposal is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, outcome.summary)
    return outcome.proposal
