"""Port contract tests for NotifierPort. Workstream C adds the WebPushNotifier factory in week 4."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from helpmate.adapters.fakes.log_notifier import LogNotifier
from helpmate.domain.models import Notification, NotificationKind
from helpmate.domain.ports import NotifierPort

FACTORIES: dict[str, Callable[[], NotifierPort]] = {
    "log": LogNotifier,
}


@pytest.fixture(params=sorted(FACTORIES))
def notifier(request) -> NotifierPort:
    return FACTORIES[request.param]()


async def test_notify_reports_the_notification_id(notifier):
    result = await notifier.notify(
        Notification(id="n1", kind=NotificationKind.TEST, title="t", body="b")
    )
    assert result.notification_id == "n1"
    assert result.delivered >= 0
    assert isinstance(notifier.name, str) and isinstance(notifier.is_fake, bool)
