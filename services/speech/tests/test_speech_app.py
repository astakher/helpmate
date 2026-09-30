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


def test_undecodable_recording_is_a_422_with_a_hint(monkeypatch):
    """A recording stopped before any sound gives a bare webm header; that's the owner's input,
    not a server error (it used to be a 500)."""
    from helpmate_speech import app as app_module
    from helpmate_speech.engines import AudioDecodeError, FakeEngine

    class Broken(FakeEngine):
        def transcribe(self, audio, mime, language):
            raise AudioDecodeError("End of file")

    monkeypatch.setattr(app_module, "load_engine", lambda settings: Broken("x"))
    with TestClient(create_app(SpeechSettings(_env_file=None))) as c:
        response = c.post(
            "/transcribe", content=b"\x1aE\xdf\xa3", headers={"Content-Type": "audio/webm"}
        )
    assert response.status_code == 422 and "hold the button" in response.json()["detail"]
