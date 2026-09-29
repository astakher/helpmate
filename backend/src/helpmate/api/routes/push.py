"""Web Push subscription management and delivery acks (Workstream C)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from helpmate.api.deps import ContainerDep, current_user
from helpmate.api.schemas.bodies import AckIn, SubscriptionIn, UnsubscribeIn, VapidKeyOut
from helpmate.domain.models import (
    Delivery,
    DeliveryResult,
    Notification,
    NotificationKind,
    PushSubscription,
    new_id,
)

router = APIRouter(prefix="/push", tags=["push"], dependencies=[Depends(current_user)])


@router.get("/vapid-public-key", response_model=VapidKeyOut)
async def vapid_public_key(container: ContainerDep) -> VapidKeyOut:
    return VapidKeyOut(public_key=container.settings.vapid_public_key or None)


@router.post("/subscriptions", status_code=status.HTTP_204_NO_CONTENT)
async def subscribe(body: SubscriptionIn, container: ContainerDep) -> None:
    await container.repos.push_subscriptions.upsert(
        PushSubscription(
            endpoint=body.endpoint,
            keys=body.keys,
            user_agent=body.user_agent,
            created_at=container.clock.now(),
        )
    )


@router.delete("/subscriptions", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe(body: UnsubscribeIn, container: ContainerDep) -> None:
    await container.repos.push_subscriptions.remove(body.endpoint)


@router.post("/test", response_model=DeliveryResult)
async def send_test(container: ContainerDep) -> DeliveryResult:
    now = container.clock.now()
    notification = Notification(
        id=new_id(),
        kind=NotificationKind.TEST,
        title="HelpMate",
        body="Notifications are working.",
        url="/settings",
        tag="helpmate-test",
        urgent=True,
        due_at=now,
    )
    await container.repos.deliveries.record(
        Delivery(notification_id=notification.id, kind=notification.kind, due_at=now, sent_at=now)
    )
    return await container.notifier.notify(notification)


@router.post("/ack", status_code=status.HTTP_204_NO_CONTENT)
async def ack(body: AckIn, container: ContainerDep) -> None:
    """Called by the service worker when a push arrives: this is how latency gets measured."""
    if not await container.repos.deliveries.ack(body.notification_id, body.received_at):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown notification")


@router.get("/deliveries", response_model=list[Delivery])
async def deliveries(container: ContainerDep) -> list[Delivery]:
    return await container.repos.deliveries.find()
