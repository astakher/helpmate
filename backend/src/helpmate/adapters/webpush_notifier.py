"""Web Push notifier (HELPMATE_NOTIFIER=webpush): Workstream C.

Sends each notification to every subscribed browser/phone through its push service (FCM for
Chrome, Mozilla's for Firefox, Apple's for Safari), encrypted end to end with the subscription's
keys and signed with our VAPID key. The payload is the JSON that web/src/sw.ts expects:
{id, kind, title, body, url, tag}; the service worker shows it and POSTs /api/push/ack.

- `ttl`: how long the push service keeps trying if the device is offline. The default 0 would drop
  a reminder if the phone is unreachable at that moment.
- `Urgency: high` for urgent notifications (reminders), so phones deliver them promptly.
- A 404/410 from the push service means the subscription is gone (unsubscribed, app removed):
  it's pruned so we stop sending to it.
- TLS is verified against certifi's CA bundle, not the OS store: Windows fetches root CAs on demand,
  so Python's view of the store can lack Apple's root and every iPhone push failed with
  CERTIFICATE_VERIFY_FAILED (web.push.apple.com) while Chrome's (FCM) worked.
"""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import aiohttp

from helpmate.domain.models import DeliveryResult, Notification, PushSubscription
from helpmate.domain.ports import PushSubscriptionRepo

log = logging.getLogger("helpmate.notify")

# (subscription_info, JSON payload, extra headers) -> HTTP status from the push service (0 = no
# response). Injectable so tests never touch the network.
Sender = Callable[[dict[str, Any], str, dict[str, str]], Awaitable[int]]


class WebPushNotifier:
    name = "webpush"
    is_fake = False

    def __init__(
        self,
        subscriptions: PushSubscriptionRepo,
        vapid_private_key: str,
        vapid_subject: str,
        ttl_seconds: int = 3600,
        send: Sender | None = None,
    ) -> None:
        if not vapid_private_key:
            raise ValueError(
                "HELPMATE_NOTIFIER=webpush needs VAPID keys. Run once, from backend/: "
                "uv run python ../scripts/gen_vapid.py --write"
            )
        self._subscriptions = subscriptions
        self._private_key = vapid_private_key
        self._subject = vapid_subject
        self._ttl = ttl_seconds
        self._send = send or self._send_webpush
        self._http: aiohttp.ClientSession | None = None  # one session, reused across pushes

    async def aclose(self) -> None:
        if self._http is not None and not self._http.closed:
            await self._http.close()
        self._http = None

    async def notify(self, notification: Notification) -> DeliveryResult:
        subscriptions = await self._subscriptions.find()
        payload = json.dumps(
            {
                "id": notification.id,
                "kind": str(notification.kind),
                "title": notification.title,
                "body": notification.body,
                "url": notification.url,
                "tag": notification.tag,
            }
        )
        headers = {"Urgency": "high" if notification.urgent else "normal"}
        outcomes = await asyncio.gather(
            *(self._deliver(sub, payload, headers) for sub in subscriptions)
        )
        delivered, gone = outcomes.count("ok"), outcomes.count("gone")
        failed = len(outcomes) - delivered - gone
        detail = f"{delivered}/{len(outcomes)} devices"
        if gone:
            detail += f", {gone} expired subscription(s) removed"
        if failed:
            detail += f", {failed} failed"
        if not subscriptions:
            detail = "no devices subscribed (Settings > Notifications > Enable)"
        log.info(
            "NOTIFY via webpush [%s] %s - %s -> %s",
            notification.kind,
            notification.title,
            notification.body,
            detail,
        )
        return DeliveryResult(notification_id=notification.id, delivered=delivered, detail=detail)

    async def _deliver(self, sub: PushSubscription, payload: str, headers: dict[str, str]) -> str:
        info = {"endpoint": sub.endpoint, "keys": sub.keys.model_dump()}
        status = await self._send(info, payload, headers)
        if 200 <= status < 300:
            return "ok"
        if status in (404, 410):
            await self._subscriptions.remove(sub.endpoint)
            return "gone"
        log.warning("push to %s… failed with status %s", sub.endpoint[:40], status or "none")
        return "failed"

    async def _session(self) -> aiohttp.ClientSession:
        import aiohttp

        if self._http is None or self._http.closed:
            connector = aiohttp.TCPConnector(ssl=push_ssl_context())
            self._http = aiohttp.ClientSession(connector=connector)
        return self._http

    async def _send_webpush(
        self, info: dict[str, Any], payload: str, headers: dict[str, str]
    ) -> int:
        import aiohttp
        from pywebpush import WebPushException, webpush_async

        try:
            response = await webpush_async(
                subscription_info=info,
                data=payload,
                vapid_private_key=self._private_key,
                vapid_claims={"sub": self._subject},  # fresh dict: pywebpush adds aud/exp to it
                ttl=self._ttl,
                headers=headers,
                timeout=10,
                aiohttp_session=await self._session(),
            )
        except WebPushException as exc:
            return exc.status_code or 0
        except (aiohttp.ClientError, OSError, TimeoutError) as exc:
            log.warning("push service unreachable: %s", exc)
            return 0
        return getattr(response, "status", 0)


def push_ssl_context() -> ssl.SSLContext:
    """TLS for the push services, verified against certifi's Mozilla CA bundle (see above)."""
    import certifi

    return ssl.create_default_context(cafile=certifi.where())
