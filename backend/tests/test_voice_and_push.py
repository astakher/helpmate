from __future__ import annotations

from datetime import timedelta

from helpmate.adapters.fakes.log_notifier import LogNotifier
from helpmate.api.routes.voice import MAX_AUDIO_BYTES


async def test_transcribe_raw_audio_body(client, settings):
    response = await client.post(
        "/api/voice/transcribe",
        content=b"\x1a\x45\xdf\xa3 not really webm",
        headers={"Content-Type": "audio/webm;codecs=opus"},
    )
    assert response.status_code == 200
    assert response.json()["text"] == settings.fake_transcript


async def test_transcribe_rejects_bad_input(client):
    wrong_type = await client.post(
        "/api/voice/transcribe", content=b"x", headers={"Content-Type": "text/plain"}
    )
    empty = await client.post(
        "/api/voice/transcribe", content=b"", headers={"Content-Type": "audio/webm"}
    )
    too_big = await client.post(
        "/api/voice/transcribe",
        content=b"0" * (MAX_AUDIO_BYTES + 1),
        headers={"Content-Type": "audio/webm"},
    )
    assert (wrong_type.status_code, empty.status_code, too_big.status_code) == (415, 422, 413)


async def test_speak_returns_wav(client):
    response = await client.post("/api/voice/speak", json={"text": "Hello there"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content[:4] == b"RIFF"


async def test_push_subscription_lifecycle(client, container):
    assert (await client.get("/api/push/vapid-public-key")).json() == {"public_key": None}
    sub = {"endpoint": "https://push.example/abc123", "keys": {"p256dh": "k", "auth": "a"}}
    assert (await client.post("/api/push/subscriptions", json=sub)).status_code == 204
    assert (await client.post("/api/push/subscriptions", json=sub)).status_code == 204  # idempotent
    assert len(await container.repos.push_subscriptions.find()) == 1
    response = await client.request(
        "DELETE", "/api/push/subscriptions", json={"endpoint": sub["endpoint"]}
    )
    assert response.status_code == 204
    assert await container.repos.push_subscriptions.find() == []


async def test_test_push_and_ack_measure_latency(client, container, clock):
    result = (await client.post("/api/push/test")).json()
    assert result["delivered"] == 1
    notifier = container.notifier
    assert isinstance(notifier, LogNotifier) and notifier.sent[-1].kind == "test"

    received = clock.now() + timedelta(seconds=2)
    ack = await client.post(
        "/api/push/ack",
        json={"notification_id": result["notification_id"], "received_at": received.isoformat()},
    )
    assert ack.status_code == 204
    [delivery] = (await client.get("/api/push/deliveries")).json()
    assert delivery["received_at"] is not None

    unknown = await client.post(
        "/api/push/ack", json={"notification_id": "nope", "received_at": received.isoformat()}
    )
    assert unknown.status_code == 404


async def test_notification_settings_round_trip(client):
    body = {
        "quiet_hours": {"start": "22:00:00", "end": "07:00:00"},
        "timezone": "America/Toronto",
        "max_per_hour": 4,
        "private_previews": True,
        "checkin_at": "20:00:00",
    }
    assert (await client.put("/api/settings/notifications", json=body)).status_code == 200
    assert (await client.get("/api/settings/notifications")).json() == body
    bad = await client.put("/api/settings/notifications", json={**body, "timezone": "Mars/Base"})
    assert bad.status_code == 422


async def test_transcribe_turns_an_unreadable_recording_into_a_422(client, container):
    from helpmate.adapters.speech_http import SpeechInputError

    class TooShort:
        name, is_fake = "stub", True

        async def transcribe(self, audio, mime, language=None):
            raise SpeechInputError("Couldn't read the recording. Hold the button while you talk.")

    container.stt = TooShort()
    response = await client.post(
        "/api/voice/transcribe", content=b"\x1aE\xdf\xa3", headers={"Content-Type": "audio/webm"}
    )
    assert response.status_code == 422 and "Hold the button" in response.json()["detail"]
