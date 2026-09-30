"""QuietHoursNotifier: Workstream C's wellbeing rules, as a decorator around any NotifierPort.

    QuietHoursNotifier(WebPushNotifier(...), repos.settings, clock)

Reads the owner's NotificationSettings (Settings page) on every call:
- urgent notifications (reminders the owner set, test pushes) always go straight through;
- non-urgent ones are HELD during quiet hours (released when they end) and beyond `max_per_hour`
  (released when the hour frees up); the result says `deferred=True`;
- `private_previews` replaces the text with a generic line ("You have a reminder") so no personal
  content passes through the push service.

Held notifications live in memory and are released by a timer, so a restart drops them. A durable
hold belongs in Workstream B's job queue; the scheduler never needs to know about any of this.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import deque
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from helpmate.domain.models import (
    DeliveryResult,
    Notification,
    NotificationKind,
    NotificationSettings,
)
from helpmate.domain.ports import Clock, NotifierPort, SettingsRepo

log = logging.getLogger("helpmate.notify")

PRIVATE_TEXT = {
    NotificationKind.REMINDER: "You have a reminder",
    NotificationKind.BRIEF: "Your brief is ready",
    NotificationKind.TEST: "Test notification",
    NotificationKind.SYSTEM: "You have a notification",
}
HOUR = timedelta(hours=1)


class QuietHoursNotifier:
    def __init__(self, inner: NotifierPort, settings: SettingsRepo, clock: Clock) -> None:
        self._inner = inner
        self._settings = settings
        self._clock = clock
        self.name = f"{inner.name}+quiet-hours"
        self.is_fake = inner.is_fake
        self._recent: deque[datetime] = deque()  # when non-urgent notifications went out
        self._held: list[tuple[datetime, Notification]] = []  # (release at, notification)
        self._timer: asyncio.Task[None] | None = None

    @property
    def held(self) -> list[Notification]:
        return [n for _, n in self._held]

    async def notify(self, notification: Notification) -> DeliveryResult:
        prefs = await self._settings.get_notification_settings()
        outgoing = private(notification) if prefs.private_previews else notification
        if not notification.urgent:
            now = self._clock.now()
            release = self._hold_until(prefs, now)
            if release is not None:
                self._held.append((release, outgoing))
                self._arm_timer()
                local = release.astimezone(ZoneInfo(prefs.timezone))
                detail = f"held until {local:%H:%M}"
                log.info("NOTIFY held [%s] %s (%s)", notification.kind, notification.title, detail)
                return DeliveryResult(
                    notification_id=notification.id, delivered=0, deferred=True, detail=detail
                )
            self._recent.append(now)
        return await self._inner.notify(outgoing)

    async def flush(self) -> int:
        """Send every held notification whose time has come (re-checking the rules)."""
        now = self._clock.now()
        due = [n for at, n in self._held if at <= now]
        self._held = [(at, n) for at, n in self._held if at > now]
        for notification in due:
            await self.notify(notification)
        if self._held:
            self._arm_timer()
        return len(due)

    async def aclose(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._timer
            self._timer = None

    def _hold_until(self, prefs: NotificationSettings, now: datetime) -> datetime | None:
        if prefs.quiet_hours is not None:
            end = quiet_hours_end(now, prefs)
            if end is not None:
                return end
        while self._recent and now - self._recent[0] >= HOUR:
            self._recent.popleft()
        if len(self._recent) >= prefs.max_per_hour:
            return self._recent[0] + HOUR
        return None

    def _arm_timer(self) -> None:
        if self._timer is not None and not self._timer.done():
            self._timer.cancel()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        wait = max(0.0, (min(at for at, _ in self._held) - self._clock.now()).total_seconds())
        self._timer = loop.create_task(self._release_after(wait), name="quiet-hours-release")

    async def _release_after(self, seconds: float) -> None:
        await asyncio.sleep(seconds)
        self._timer = None
        try:
            await self.flush()
        except Exception:
            log.exception("releasing held notifications failed")


def quiet_hours_end(now: datetime, prefs: NotificationSettings) -> datetime | None:
    """If `now` is inside the owner's quiet hours, when they end; otherwise None."""
    if prefs.quiet_hours is None:
        return None
    tz = ZoneInfo(prefs.timezone)
    local = now.astimezone(tz)
    start, end = prefs.quiet_hours.start, prefs.quiet_hours.end
    t = local.time().replace(tzinfo=None)
    inside = start <= t < end if start <= end else (t >= start or t < end)  # may wrap midnight
    if not inside or start == end:
        return None
    end_at = datetime.combine(local.date(), end, tzinfo=tz)  # wall-clock end, DST-safe
    return end_at if end_at > local else end_at + timedelta(days=1)


def private(notification: Notification) -> Notification:
    """Same notification with generic text, for the push service and the lock screen."""
    return notification.model_copy(
        update={"title": "HelpMate", "body": PRIVATE_TEXT.get(notification.kind, "HelpMate")}
    )
