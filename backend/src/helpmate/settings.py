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
    mail: Literal["fake", "gmail"] = "fake"
    calendar: Literal["fake", "google"] = "fake"

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
    ollama_embed_on_cpu: bool = True  # keep the 4 GB GPU for the chat model
    ollama_think: bool | None = None  # set False for qwen3 to skip "thinking" output

    # --- Memory search (agent answers use the owner's approved facts) ---
    memory_top_k: int = 3
    memory_min_score: float = 0.55  # cosine; tuned for nomic-embed-text (eval/memory_recall.py)

    # --- Speech service ---
    speech_url: str = "http://127.0.0.1:8001"

    # --- Auth: HELPMATE_AUTH=totp (Workstream B stand-in) ---
    owner_username: str = "owner"
    owner_password_hash: SecretStr = SecretStr("")  # argon2; set with scripts/set_password.py
    auth_state_file: Path = REPO_ROOT / "data" / "auth.json"  # TOTP secret (data/ is git-ignored)
    session_days: int = 7

    # --- Gmail + Google Calendar (Workstream B stand-in) ---
    google_token_file: Path = REPO_ROOT / "data" / "google_token.json"  # scripts/google_auth.py
    day_start_hour: int = 9  # find_free_time only offers time between these local hours
    day_end_hour: int = 18

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
