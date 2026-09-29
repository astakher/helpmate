from __future__ import annotations

import io
import math
import struct
import wave

from helpmate.domain.models import Transcript


class FakeSTT:
    """Returns a fixed transcript (HELPMATE_FAKE_TRANSCRIPT), so the push-to-talk flow works end
    to end without the speech service. The audio bytes are ignored and never stored."""

    name = "fake"
    is_fake = True

    def __init__(self, transcript: str) -> None:
        self._transcript = transcript

    async def transcribe(self, audio: bytes, mime: str, language: str | None = None) -> Transcript:
        return Transcript(text=self._transcript, language=language or "en", duration_ms=0, stt_ms=0)


class FakeTTS:
    """Returns a short beep as WAV, so the speaker path can be exercised without Kokoro."""

    name = "fake"
    is_fake = True

    async def speak(self, text: str, voice: str | None = None) -> bytes:
        return beep_wav(seconds=min(0.15 + 0.01 * len(text.split()), 0.6))


def beep_wav(seconds: float = 0.25, freq: float = 660.0, rate: int = 16_000) -> bytes:
    frames = int(seconds * rate)
    fade = max(1, int(0.01 * rate))
    samples = bytearray()
    for i in range(frames):
        envelope = min(1.0, i / fade, (frames - i) / fade)
        value = int(0.3 * envelope * 32767 * math.sin(2 * math.pi * freq * i / rate))
        samples += struct.pack("<h", value)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(samples))
    return buf.getvalue()
