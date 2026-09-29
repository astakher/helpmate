from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# src/helpmate_speech/settings.py -> parents: helpmate_speech, src, speech, services, <repo root>
REPO_ROOT = Path(__file__).resolve().parents[4]
SERVICE_ROOT = Path(__file__).resolve().parents[2]


class SpeechSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SPEECH_",
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    engine: Literal["fake", "real"] = "fake"
    host: str = "127.0.0.1"  # loopback only: the core calls us, nothing else should
    port: int = 8001

    # faster-whisper
    whisper_model: str = "base"  # tiny | base | small (multilingual); *.en = English only
    whisper_language: str | None = None  # None = auto-detect
    cpu_threads: int = 4

    # Kokoro (kokoro-onnx)
    kokoro_model: Path = SERVICE_ROOT / "models" / "kokoro-v1.0.int8.onnx"
    kokoro_voices: Path = SERVICE_ROOT / "models" / "voices-v1.0.bin"
    kokoro_voice: str = "af_heart"

    fake_transcript: str = "remind me to stretch in 1 minute"
