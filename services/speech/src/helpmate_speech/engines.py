"""Speech engines. `FakeEngine` needs no models; `load_engine("real")` arrives in Phase 5
(faster-whisper + kokoro-onnx)."""

from __future__ import annotations

import io
import math
import struct
import wave
from typing import Protocol

from pydantic import BaseModel

from helpmate_speech.settings import SpeechSettings


class TranscriptOut(BaseModel):
    """Same shape as helpmate.domain.models.Transcript in the core."""

    text: str
    language: str | None = None
    duration_ms: int
    stt_ms: int


class Engine(Protocol):
    name: str
    stt_model: str
    tts_model: str

    def transcribe(self, audio: bytes, mime: str, language: str | None) -> TranscriptOut: ...

    def speak(self, text: str, voice: str | None) -> bytes: ...


class FakeEngine:
    name = "fake"
    stt_model = "none"
    tts_model = "none"

    def __init__(self, transcript: str) -> None:
        self._transcript = transcript

    def transcribe(self, audio: bytes, mime: str, language: str | None) -> TranscriptOut:
        return TranscriptOut(
            text=self._transcript, language=language or "en", duration_ms=0, stt_ms=0
        )

    def speak(self, text: str, voice: str | None) -> bytes:
        return tone_wav(seconds=min(0.15 + 0.01 * len(text.split()), 0.6))


def load_engine(settings: SpeechSettings) -> Engine:
    if settings.engine == "fake":
        return FakeEngine(settings.fake_transcript)
    raise NotImplementedError("SPEECH_ENGINE=real arrives in Phase 5 (faster-whisper + Kokoro)")


def tone_wav(seconds: float = 0.25, freq: float = 660.0, rate: int = 16_000) -> bytes:
    frames = int(seconds * rate)
    fade = max(1, int(0.01 * rate))
    samples = bytearray()
    for i in range(frames):
        envelope = min(1.0, i / fade, (frames - i) / fade)
        samples += struct.pack(
            "<h", int(0.3 * envelope * 32767 * math.sin(2 * math.pi * freq * i / rate))
        )
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(samples))
    return buf.getvalue()
