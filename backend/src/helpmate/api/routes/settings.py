from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, status

from helpmate.api.deps import ContainerDep, current_user
from helpmate.domain.models import NotificationSettings

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(current_user)])


@router.get("/notifications", response_model=NotificationSettings)
async def get_notification_settings(container: ContainerDep) -> NotificationSettings:
    return await container.repos.settings.get_notification_settings()


@router.put("/notifications", response_model=NotificationSettings)
async def put_notification_settings(
    body: NotificationSettings, container: ContainerDep
) -> NotificationSettings:
    try:
        ZoneInfo(body.timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"unknown timezone {body.timezone!r}"
        ) from exc
    await container.repos.settings.put_notification_settings(body)
    return body
