"""Port contract tests for NotifierPort, run against the fake and Part C's real notifiers."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from helpmate.adapters.clock import FakeClock
from helpmate.adapters.fakes.log_notifier import LogNotifier
from helpmate.adapters.fakes.memory_repos import (
    InMemoryPushSubscriptionRepo,
    InMemorySettingsRepo,
)
from helpmate.adapters.quiet_hours import QuietHoursNotifier
from helpmate.adapters.webpush_notifier import WebPushNotifier
from helpmate.domain.models import Notification, NotificationKind
from helpmate.domain.ports import NotifierPort


async def _accept(info: dict, payload: str, headers: dict[str, str]) -> int:
    return 201  # a push service that accepts everything; no network


def _webpush() -> NotifierPort:
    return WebPushNotifier(
        InMemoryPushSubscriptionRepo(), "k" * 43, "mailto:x@example.com", send=_accept
    )


def _webpush_quiet_hours() -> NotifierPort:
    clock = FakeClock(datetime(2026, 10, 5, 12, 0, tzinfo=ZoneInfo("America/Toronto")))
    return QuietHoursNotifier(_webpush(), InMemorySettingsRepo(), clock)


FACTORIES: dict[str, Callable[[], NotifierPort]] = {
    "log": LogNotifier,
    "webpush": _webpush,
    "webpush+quiet-hours": _webpush_quiet_hours,
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
