"""Speech engines. `FakeEngine` needs no models. `RealEngine` (SPEECH_ENGINE=real) runs
faster-whisper (STT) and Kokoro via kokoro-onnx (TTS) on the CPU; install it with
`uv sync --extra real` and download the Kokoro files with `./scripts/get_models.ps1`.

Audio stays in memory: faster-whisper decodes the uploaded bytes from a BytesIO (PyAV bundles
FFmpeg, so webm/opus, mp4 and ogg all work) and nothing is written to disk.
"""

from __future__ import annotations

import io
import logging
import math
import struct
import time
import wave
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel

from helpmate_speech.settings import SpeechSettings

if TYPE_CHECKING:
    import numpy as np

log = logging.getLogger("helpmate.speech")


class AudioDecodeError(ValueError):
    """The upload isn't decodable audio, e.g. a recording stopped before any sound was captured
    (the browser then sends a bare container header). The app answers 422, not 500."""


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


class RealEngine:
    """faster-whisper + Kokoro on the CPU. Blocking: the app calls it from a worker thread."""

    name = "real"

    def __init__(self, settings: SpeechSettings) -> None:
        missing = [p for p in (settings.kokoro_model, settings.kokoro_voices) if not p.exists()]
        if missing:  # checked before the heavy imports, so the hint works without the extra too
            raise FileNotFoundError(
                f"Kokoro model files missing: {', '.join(p.name for p in missing)}. From the repo "
                "root run ./scripts/get_models.ps1 (and `uv sync --extra real` in services/speech)."
            )
        from faster_whisper import WhisperModel
        from kokoro_onnx import Kokoro

        started = time.perf_counter()
        # int8 on CPU: ~0.5 GB RAM for `base`; the model downloads on first use (~145 MB)
        self._whisper = WhisperModel(
            settings.whisper_model,
            device="cpu",
            compute_type="int8",
            cpu_threads=settings.cpu_threads,
        )
        self._kokoro = Kokoro(str(settings.kokoro_model), str(settings.kokoro_voices))
        self._voices = set(self._kokoro.get_voices())
        self._default_voice = (
            settings.kokoro_voice if settings.kokoro_voice in self._voices else "af_heart"
        )
        self.stt_model = f"faster-whisper:{settings.whisper_model} (int8, cpu)"
        self.tts_model = f"kokoro:{settings.kokoro_model.name}"
        self._warm_up()
        log.info("real engine loaded in %.1f s", time.perf_counter() - started)

    def transcribe(self, audio: bytes, mime: str, language: str | None) -> TranscriptOut:
        import av

        started = time.perf_counter()
        try:
            segments, info = self._whisper.transcribe(
                io.BytesIO(audio),
                language=language or None,  # None = auto-detect (multilingual model)
                beam_size=1,
                vad_filter=True,
                condition_on_previous_text=False,
            )
            text = " ".join(segment.text.strip() for segment in segments).strip()  # runs the model
        except av.error.FFmpegError as exc:  # EOFError / InvalidDataError from PyAV
            raise AudioDecodeError(f"couldn't read the recording ({mime}): {exc}") from exc
        return TranscriptOut(
            text=text,
            language=info.language,
            duration_ms=int(info.duration * 1000),
            stt_ms=int((time.perf_counter() - started) * 1000),
        )

    def speak(self, text: str, voice: str | None) -> bytes:
        chosen = voice if voice in self._voices else self._default_voice
        lang = {"a": "en-us", "b": "en-gb"}.get(chosen[:1], "en-us")  # af_*/am_* US, bf_*/bm_* UK
        samples, rate = self._kokoro.create(text, voice=chosen, speed=1.0, lang=lang)
        return wav_bytes(samples, rate)

    def _warm_up(self) -> None:
        """First inference is slow (graph set-up); pay it at start-up, not on the owner's first
        request."""
        self.speak("Ready.", None)
        self.transcribe(tone_wav(0.5), "audio/wav", "en")


def load_engine(settings: SpeechSettings) -> Engine:
    if settings.engine == "fake":
        return FakeEngine(settings.fake_transcript)
    return RealEngine(settings)


def wav_bytes(samples: np.ndarray, rate: int) -> bytes:
    """float32 samples in [-1, 1] -> 16-bit mono WAV."""
    import numpy as np

    pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


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
