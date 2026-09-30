"""Part C speech adapters against mocked HTTP: no speech service needed."""

from __future__ import annotations

import httpx
import pytest

from helpmate.adapters.speech_http import HttpSTT, HttpTTS, SpeechServiceUnavailable


def _down(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("refused", request=request)


async def test_http_stt_sends_raw_audio():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["type"] = request.headers["content-type"]
        seen["body"] = request.content
        seen["language"] = request.url.params.get("language")
        return httpx.Response(
            200, json={"text": "hi", "language": "en", "duration_ms": 900, "stt_ms": 300}
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://speech")
    transcript = await HttpSTT(client).transcribe(b"opus-bytes", "audio/webm;codecs=opus", "en")
    assert transcript.text == "hi" and transcript.stt_ms == 300
    assert seen == {"type": "audio/webm;codecs=opus", "body": b"opus-bytes", "language": "en"}


async def test_http_stt_down():
    client = httpx.AsyncClient(transport=httpx.MockTransport(_down), base_url="http://speech")
    with pytest.raises(SpeechServiceUnavailable):
        await HttpSTT(client).transcribe(b"x", "audio/webm")


async def test_http_tts_returns_wav_and_reports_down():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["json"] = request.read().decode()
        return httpx.Response(200, content=b"RIFF....WAVE", headers={"content-type": "audio/wav"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://speech")
    tts = HttpTTS(client)
    assert await tts.speak("hello", "af_heart") == b"RIFF....WAVE"
    assert seen["path"] == "/speak" and '"voice":"af_heart"' in seen["json"].replace(" ", "")
    assert tts.name == "http:http://speech" and not tts.is_fake

    down = httpx.AsyncClient(transport=httpx.MockTransport(_down), base_url="http://speech")
    with pytest.raises(SpeechServiceUnavailable):
        await HttpTTS(down).speak("hello")
