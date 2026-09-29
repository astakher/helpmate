from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from helpmate.agent.policy import InvalidToolArgs, ProposalAlreadyDecided, ProposalNotFound
from helpmate.api.deps import ContainerDep, current_user
from helpmate.api.schemas.bodies import DecisionIn
from helpmate.domain.models import Proposal, ProposalStatus

router = APIRouter(prefix="/proposals", tags=["proposals"], dependencies=[Depends(current_user)])


@router.get("", response_model=list[Proposal])
async def list_proposals(
    container: ContainerDep, status: ProposalStatus | None = None
) -> list[Proposal]:
    return await container.repos.proposals.find(status)


@router.get("/{proposal_id}", response_model=Proposal)
async def get_proposal(proposal_id: str, container: ContainerDep) -> Proposal:
    proposal = await container.repos.proposals.get(proposal_id)
    if proposal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "proposal not found")
    return proposal


@router.post("/{proposal_id}/decision", response_model=Proposal)
async def decide(proposal_id: str, body: DecisionIn, container: ContainerDep) -> Proposal:
    """Approve, edit-then-approve, or reject. The only way an agent write ever executes."""
    try:
        return await container.policy.decide(proposal_id, body.decision, body.args)
    except ProposalNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "proposal not found") from exc
    except ProposalAlreadyDecided as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except InvalidToolArgs as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
