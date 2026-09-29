from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from helpmate_speech.app import create_app
from helpmate_speech.settings import SpeechSettings


@pytest.fixture
def client():
    settings = SpeechSettings(_env_file=None, engine="fake", fake_transcript="add task buy milk")
    with TestClient(create_app(settings)) as c:
        yield c


def test_health(client):
    assert client.get("/health").json()["engine"] == "fake"


def test_transcribe_raw_body(client):
    response = client.post(
        "/transcribe?language=en", content=b"audio", headers={"Content-Type": "audio/webm"}
    )
    assert response.status_code == 200
    assert response.json() == {
        "text": "add task buy milk",
        "language": "en",
        "duration_ms": 0,
        "stt_ms": 0,
    }


def test_transcribe_rejects_empty(client):
    assert (
        client.post("/transcribe", content=b"", headers={"Content-Type": "audio/webm"}).status_code
        == 422
    )


def test_speak_returns_wav(client):
    response = client.post("/speak", json={"text": "hello"})
    assert response.headers["content-type"] == "audio/wav"
    assert response.content[:4] == b"RIFF"
