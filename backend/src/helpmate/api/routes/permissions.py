# Stand-in for Workstream A - not part of the Part C deliverable
"""The pre-approved actions (O6's "permitted" tier): GET/PUT /api/settings/permissions.

Empty by default. Only tools that change HelpMate's own data can be on the list (the policy
engine's `pre_approvable`); a tool that sends something out (email, calendar) is refused here and
ignored by the policy engine even if it were stored."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from helpmate.agent.policy import pre_approvable
from helpmate.api.deps import ContainerDep, current_user
from helpmate.api.schemas.bodies import PermissionsIn, PermissionsOut
from helpmate.container import Container
from helpmate.domain.models import PermissionSettings

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(current_user)])


def _eligible(container: Container) -> list[str]:
    return [t.name for t in container.policy.tools.all() if pre_approvable(t)]


@router.get("/permissions", response_model=PermissionsOut)
async def get_permissions(container: ContainerDep) -> PermissionsOut:
    stored = await container.repos.settings.get_permissions()
    eligible = _eligible(container)
    return PermissionsOut(
        permitted=[n for n in stored.permitted if n in eligible], eligible=eligible
    )


@router.put("/permissions", response_model=PermissionsOut)
async def put_permissions(body: PermissionsIn, container: ContainerDep) -> PermissionsOut:
    eligible = _eligible(container)
    refused = [name for name in body.permitted if name not in eligible]
    if refused:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"These can't be pre-approved: {', '.join(refused)}. Only actions that change "
            "HelpMate's own data can; emails and calendar events always ask you first.",
        )
    permitted = list(dict.fromkeys(body.permitted))  # no duplicates, in the owner's order
    await container.repos.settings.put_permissions(PermissionSettings(permitted=permitted))
    return PermissionsOut(permitted=permitted, eligible=eligible)
