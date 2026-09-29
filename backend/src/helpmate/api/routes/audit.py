from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from helpmate.api.deps import ContainerDep, current_user
from helpmate.domain.models import AuditEntry

router = APIRouter(tags=["audit"], dependencies=[Depends(current_user)])


@router.get("/audit", response_model=list[AuditEntry])
async def list_audit(
    container: ContainerDep, limit: int = Query(default=100, ge=1, le=1000)
) -> list[AuditEntry]:
    return await container.repos.audit.find(limit)
