"""WebPushNotifier (Part C) against a fake push service: no network, no browser."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from helpmate.adapters.fakes.memory_repos import InMemoryPushSubscriptionRepo
from helpmate.adapters.webpush_notifier import WebPushNotifier
from helpmate.domain.models import Notification, NotificationKind, PushKeys, PushSubscription

NOW = datetime(2026, 10, 5, 16, 0, tzinfo=UTC)
GEN_VAPID = str(Path(__file__).resolve().parents[2] / "scripts" / "gen_vapid.py")


def subscription(endpoint: str) -> PushSubscription:
    return PushSubscription(
        endpoint=endpoint, keys=PushKeys(p256dh="p256", auth="auth"), created_at=NOW
    )


class FakePushService:
    def __init__(self, status_by_endpoint: dict[str, int] | None = None) -> None:
        self.status = status_by_endpoint or {}
        self.sent: list[tuple[dict, dict, dict]] = []

    async def __call__(self, info: dict, payload: str, headers: dict[str, str]) -> int:
        self.sent.append((info, json.loads(payload), headers))
        return self.status.get(info["endpoint"], 201)


async def notifier_with(*endpoints: str, status=None):
    repo = InMemoryPushSubscriptionRepo()
    for endpoint in endpoints:
        await repo.upsert(subscription(endpoint))
    service = FakePushService(status)
    return (
        WebPushNotifier(repo, "k" * 43, "mailto:owner@example.com", 3600, send=service),
        repo,
        service,
    )


REMINDER = Notification(
    id="n1",
    kind=NotificationKind.REMINDER,
    title="Reminder",
    body="call mom",
    url="/reminders",
    tag="reminder-r1",
    urgent=True,
)


async def test_sends_the_service_worker_payload_to_every_device():
    notifier, _, service = await notifier_with("https://push/a", "https://push/b")
    result = await notifier.notify(REMINDER)

    assert result.delivered == 2 and result.detail == "2/2 devices" and not result.deferred
    info, payload, headers = service.sent[0]
    assert payload == {
        "id": "n1",
        "kind": "reminder",
        "title": "Reminder",
        "body": "call mom",
        "url": "/reminders",
        "tag": "reminder-r1",
    }  # exactly what web/src/sw.ts reads
    assert info["keys"] == {"p256dh": "p256", "auth": "auth"}
    assert headers == {"Urgency": "high"}


async def test_expired_subscriptions_are_pruned_and_failures_reported():
    notifier, repo, _ = await notifier_with(
        "https://push/ok",
        "https://push/gone",
        "https://push/down",
        status={"https://push/gone": 410, "https://push/down": 500},
    )
    result = await notifier.notify(REMINDER.model_copy(update={"urgent": False}))
    assert result.delivered == 1
    assert "1 expired subscription(s) removed" in result.detail and "1 failed" in result.detail
    assert [s.endpoint for s in await repo.find()] == ["https://push/ok", "https://push/down"]


async def test_no_devices_says_how_to_subscribe():
    notifier, _, _ = await notifier_with()
    result = await notifier.notify(REMINDER)
    assert result.delivered == 0 and "Enable" in result.detail


def test_missing_vapid_key_explains_the_fix():
    with pytest.raises(ValueError, match="gen_vapid.py --write"):
        WebPushNotifier(InMemoryPushSubscriptionRepo(), "", "mailto:x@example.com")


async def test_real_pywebpush_accepts_keys_from_gen_vapid_offline(tmp_path, monkeypatch):
    """The key format scripts/gen_vapid.py writes is what pywebpush signs with. curl=True builds
    the exact request without sending it, so this runs offline in CI. (It also writes the body to
    ./encrypted.data, hence the temporary working directory.)"""
    monkeypatch.chdir(tmp_path)
    import base64
    import os
    import runpy

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from pywebpush import webpush_async

    gen = runpy.run_path(GEN_VAPID)
    public, private = gen["generate"]()
    assert len(base64.urlsafe_b64decode(public + "=")) == 65  # the browser's applicationServerKey

    browser = ec.generate_private_key(ec.SECP256R1())  # stands in for the browser's push keys
    point = browser.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    subscription = {
        "endpoint": "https://fcm.googleapis.com/fcm/send/abc",
        "keys": {"p256dh": gen["b64url"](point), "auth": gen["b64url"](os.urandom(16))},
    }
    request = await webpush_async(
        subscription,
        data='{"id": "n1", "title": "Reminder", "body": "call mom"}',
        vapid_private_key=private,
        vapid_claims={"sub": "mailto:owner@example.com"},
        ttl=3600,
        headers={"Urgency": "high"},
        curl=True,
    )
    assert "authorization: vapid t=" in request and "ttl: 3600" in request
    assert "content-encoding: aes128gcm" in request and "urgency: high" in request
