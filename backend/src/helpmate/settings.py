"""Configuration from environment variables (prefix HELPMATE_) and the repo-root .env file."""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# src/helpmate/settings.py -> parents: helpmate, src, backend, <repo root>
REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="HELPMATE_",
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Adapter selection: the plug-in switches (see docs/plan.md §3) ---
    agent: Literal["scripted", "loop"] = "scripted"
    llm: Literal["fake", "ollama"] = "fake"
    repo: Literal["memory", "postgres"] = "memory"
    scheduler: Literal["dev", "pg"] = "dev"
    notifier: Literal["log", "webpush"] = "log"
    stt: Literal["fake", "http"] = "fake"
    tts: Literal["fake", "http"] = "fake"
    auth: Literal["dev", "totp"] = "dev"

    # --- Core ---
    timezone: str = "America/Toronto"
    host: str = "127.0.0.1"
    port: int = 8000
    reload: bool = False
    serve_web: bool = False  # prod mode: serve the built web app at /
    web_dist: Path = REPO_ROOT / "web" / "dist"

    # --- Scheduler (dev) ---
    scheduler_tick_seconds: float = 5.0
    scheduler_autostart: bool = True

    # --- Fakes ---
    fake_stream_delay_seconds: float = 0.03  # simulated token streaming speed
    fake_transcript: str = "remind me to stretch in 1 minute"

    # --- Ollama (inference plane) ---
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.2:3b"
    ollama_embed_model: str = "nomic-embed-text"
    ollama_think: bool | None = None  # set False for qwen3 to skip "thinking" output

    # --- Speech service ---
    speech_url: str = "http://127.0.0.1:8001"

    # --- Postgres / S3 (Workstream B) ---
    database_url: str | None = None
    s3_endpoint: str | None = None

    # --- Web Push (Workstream C) ---
    vapid_public_key: str = ""
    vapid_private_key: SecretStr = SecretStr("")
    vapid_subject: str = "mailto:owner@example.com"
    push_ttl_seconds: int = 3600

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)
