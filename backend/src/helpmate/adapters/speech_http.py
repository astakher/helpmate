"""Speech adapters (HELPMATE_STT=http / HELPMATE_TTS=http): Workstream C.

They call the separate speech service (services/speech) that runs faster-whisper and Kokoro
on the inference plane. The audio goes over loopback HTTP and is never written to disk.
"""

from __future__ import annotations

import httpx

from helpmate.domain.models import Transcript


class SpeechServiceUnavailable(RuntimeError):
    pass


class SpeechInputError(ValueError):
    """The speech service rejected the input itself (e.g. a recording too short to decode).
    The voice route answers 422 with this message instead of a 500."""


class HttpSTT:
    is_fake = False

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client
        self.name = f"http:{client.base_url}"

    async def transcribe(self, audio: bytes, mime: str, language: str | None = None) -> Transcript:
        # raw body, not multipart: nothing is spooled to a temp file on either side
        params = {"language": language} if language else {}
        try:
            response = await self._client.post(
                "/transcribe", content=audio, headers={"Content-Type": mime}, params=params
            )
        except httpx.ConnectError as exc:
            raise SpeechServiceUnavailable(
                f"speech service not reachable at {self._client.base_url}"
            ) from exc
        if response.status_code == 422:
            raise SpeechInputError(_detail(response))
        response.raise_for_status()
        return Transcript.model_validate(response.json())


class HttpTTS:
    is_fake = False

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client
        self.name = f"http:{client.base_url}"

    async def speak(self, text: str, voice: str | None = None) -> bytes:
        try:
            response = await self._client.post("/speak", json={"text": text, "voice": voice})
        except httpx.ConnectError as exc:
            raise SpeechServiceUnavailable(
                f"speech service not reachable at {self._client.base_url}"
            ) from exc
        response.raise_for_status()
        return response.content


def _detail(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail")
    except ValueError:
        detail = None
    return detail if isinstance(detail, str) else "the speech service couldn't use that audio"
