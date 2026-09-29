from __future__ import annotations

from fastapi import APIRouter

from helpmate import __version__
from helpmate.api.deps import ContainerDep
from helpmate.api.schemas.bodies import AdapterInfo, HealthOut

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut)
async def health(container: ContainerDep) -> HealthOut:
    """Which adapter is plugged into each seam: the System status page reads this."""
    return HealthOut(
        version=__version__,
        adapters={
            seam: AdapterInfo(name=adapter.name, fake=adapter.is_fake)
            for seam, adapter in container.adapters().items()
        },
    )
