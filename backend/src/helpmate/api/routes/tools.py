from __future__ import annotations

from fastapi import APIRouter, Depends

from helpmate.api.deps import ContainerDep, current_user
from helpmate.api.schemas.bodies import ToolInfo

router = APIRouter(tags=["tools"], dependencies=[Depends(current_user)])


@router.get("/tools", response_model=list[ToolInfo])
async def list_tools(container: ContainerDep) -> list[ToolInfo]:
    """The agent's tools and their argument schemas (the approval card's Edit form uses these)."""
    return [
        ToolInfo(
            name=tool.name,
            description=tool.description,
            read_only=tool.read_only,
            risk=tool.risk,
            parameters=tool.args_model.model_json_schema(),
        )
        for tool in container.tools.all()
    ]
