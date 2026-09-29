from __future__ import annotations

import logging

from helpmate.domain.models import DeliveryResult, Notification

log = logging.getLogger("helpmate.notify")


class LogNotifier:
    """Prints notifications to the server log (HELPMATE_NOTIFIER=log). Keeps them in `sent`
    for tests."""

    name = "log"
    is_fake = True

    def __init__(self) -> None:
        self.sent: list[Notification] = []

    async def notify(self, notification: Notification) -> DeliveryResult:
        log.info("NOTIFY [%s] %s - %s", notification.kind, notification.title, notification.body)
        self.sent.append(notification)
        return DeliveryResult(notification_id=notification.id, delivered=1, detail="logged")
