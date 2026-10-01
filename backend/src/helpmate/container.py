"""Composition root: the one place that turns settings into concrete adapters.

To plug in a real adapter, replace the matching `_not_yet(...)` branch below with it, then flip
the HELPMATE_* variable in .env. Nothing else in the codebase changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import NoReturn

import httpx

from helpmate.adapters.clock import SystemClock
from helpmate.adapters.fakes.connectors import FakeCalendar, FakeMail
from helpmate.adapters.fakes.dev_auth import DevAuth
from helpmate.adapters.fakes.dev_scheduler import DevScheduler
from helpmate.adapters.fakes.fake_llm import FakeEmbeddings, FakeLLM
from helpmate.adapters.fakes.fake_speech import FakeSTT, FakeTTS
from helpmate.adapters.fakes.log_notifier import LogNotifier
from helpmate.adapters.fakes.memory_files import InMemoryFileStore
from helpmate.adapters.fakes.memory_repos import InMemoryRepositories
from helpmate.adapters.fakes.scripted_agent import ScriptedAgent
from helpmate.adapters.quiet_hours import QuietHoursNotifier
from helpmate.adapters.speech_http import HttpSTT, HttpTTS
from helpmate.adapters.webpush_notifier import WebPushNotifier
from helpmate.agent.documents import DocumentLibrary
from helpmate.agent.policy import PolicyEngine
from helpmate.agent.tools import ToolDeps, ToolRegistry, default_registry
from helpmate.agent.triage import Triage
from helpmate.domain.ports import (
    Adapter,
    AgentPort,
    AuthPort,
    CalendarPort,
    Clock,
    EmbeddingPort,
    FileStorePort,
    LLMPort,
    MailPort,
    NotifierPort,
    Repositories,
    SchedulerPort,
    STTPort,
    TTSPort,
)
from helpmate.settings import Settings

_OWNER = {
    "agent": "A",
    "llm": "A",
    "repo": "B",
    "scheduler": "B",
    "auth": "B",
    "mail": "B",
    "calendar": "B",
    "files": "B",
    "notifier": "C",
    "stt": "C",
    "tts": "C",
}


class AdapterNotImplemented(RuntimeError):
    pass


def _not_yet(seam: str, choice: str) -> NoReturn:
    raise AdapterNotImplemented(
        f"HELPMATE_{seam.upper()}={choice} is Workstream {_OWNER[seam]}'s adapter and is not "
        f"implemented yet. Use the fake for now (see .env.example)."
    )


@dataclass
class Container:
    settings: Settings
    clock: Clock
    repos: Repositories
    auth: AuthPort
    llm: LLMPort
    embeddings: EmbeddingPort
    stt: STTPort
    tts: TTSPort
    notifier: NotifierPort
    scheduler: SchedulerPort
    mail: MailPort
    calendar: CalendarPort
    tools: ToolRegistry
    policy: PolicyEngine
    agent: AgentPort
    triage: Triage
    files: FileStorePort
    library: DocumentLibrary
    _http_clients: list[httpx.AsyncClient] = field(default_factory=list)

    def adapters(self) -> dict[str, Adapter]:
        return {
            "agent": self.agent,
            "llm": self.llm,
            "embeddings": self.embeddings,
            "repo": self.repos,
            "scheduler": self.scheduler,
            "auth": self.auth,
            "mail": self.mail,
            "calendar": self.calendar,
            "files": self.files,
            "notifier": self.notifier,
            "stt": self.stt,
            "tts": self.tts,
        }

    async def startup(self) -> None:
        if isinstance(self.repos, InMemoryRepositories):
            await self.repos.seed(self.clock.now(), self.settings.timezone)
        elif (start := getattr(self.repos, "startup", None)) is not None:
            await start(
                self.clock.now(), self.settings.timezone
            )  # Postgres: migrate, seed if empty
        if self.settings.scheduler_autostart:
            await self.scheduler.start()

    async def shutdown(self) -> None:
        await self.scheduler.stop()
        if (close := getattr(self.notifier, "aclose", None)) is not None:
            await close()  # e.g. QuietHoursNotifier's release timer
        for client in self._http_clients:
            await client.aclose()
        if (close_repos := getattr(self.repos, "close", None)) is not None:
            await close_repos()  # e.g. the Postgres connection pool


def build_container(settings: Settings, clock: Clock | None = None) -> Container:
    clock = clock or SystemClock()
    http_clients: list[httpx.AsyncClient] = []

    def http_client(base_url: str, timeout: httpx.Timeout) -> httpx.AsyncClient:
        client = httpx.AsyncClient(base_url=base_url, timeout=timeout)
        http_clients.append(client)
        return client

    # --- Persistence (B) ---
    repos: Repositories
    if settings.repo == "memory":
        repos = InMemoryRepositories()
    else:
        # Stand-in for Workstream B - not part of the Part C deliverable
        from helpmate.adapters.postgres_repos import PostgresRepositories

        repos = PostgresRepositories(settings.database_url or "")

    # --- Auth (B) ---
    auth: AuthPort
    if settings.auth == "dev":
        auth = DevAuth()
    else:
        # Stand-in for Workstream B - not part of the Part C deliverable
        from helpmate.adapters.totp_auth import TotpAuth

        auth = TotpAuth(
            settings.owner_username,
            settings.owner_password_hash.get_secret_value(),
            settings.auth_state_file,
            clock,
            timedelta(days=settings.session_days),
        )

    # --- Notifications (C) ---
    notifier: NotifierPort
    if settings.notifier == "log":
        notifier = LogNotifier()
    else:
        webpush = WebPushNotifier(
            repos.push_subscriptions,
            settings.vapid_private_key.get_secret_value(),
            settings.vapid_subject,
            settings.push_ttl_seconds,
        )
        notifier = QuietHoursNotifier(webpush, repos.settings, clock)

    # --- Scheduler (B) ---
    scheduler: SchedulerPort
    if settings.scheduler == "dev":
        scheduler = DevScheduler(
            repos, notifier, clock, settings.scheduler_tick_seconds, tz=settings.tz
        )
    else:
        # Stand-in for Workstream B - not part of the Part C deliverable
        from helpmate.adapters.postgres_jobs import PostgresJobStore
        from helpmate.adapters.postgres_repos import PostgresRepositories
        from helpmate.worker.scheduler import JobScheduler

        if not isinstance(repos, PostgresRepositories):
            raise AdapterNotImplemented(
                "HELPMATE_SCHEDULER=pg keeps its queue in Postgres: set HELPMATE_REPO=postgres too."
            )
        scheduler = JobScheduler(
            PostgresJobStore(repos.db), repos, notifier, clock, settings.tz, name="pg"
        )

    # --- LLM + embeddings (A) ---
    llm: LLMPort
    embeddings: EmbeddingPort
    if settings.llm == "fake":
        llm = FakeLLM(settings.fake_stream_delay_seconds)
        embeddings = FakeEmbeddings()
    else:
        from helpmate.adapters.ollama_llm import OllamaEmbeddings, OllamaLLM

        ollama = http_client(settings.ollama_url, httpx.Timeout(120.0, connect=5.0))
        # temperature 0: routing and tool calls were benchmarked that way (stand-in for A)
        llm = OllamaLLM(
            ollama, settings.ollama_model, think=settings.ollama_think, options={"temperature": 0}
        )
        embeddings = OllamaEmbeddings(
            ollama, settings.ollama_embed_model, on_cpu=settings.ollama_embed_on_cpu
        )

    # --- Speech (C) ---
    stt: STTPort = FakeSTT(settings.fake_transcript)
    tts: TTSPort = FakeTTS()
    if "http" in (settings.stt, settings.tts):
        speech = http_client(settings.speech_url, httpx.Timeout(60.0, connect=3.0))
        if settings.stt == "http":
            stt = HttpSTT(speech)
        if settings.tts == "http":
            tts = HttpTTS(speech)

    # --- Files: uploaded documents' bytes (B) ---
    files: FileStorePort
    if settings.files == "memory":
        files = InMemoryFileStore()
    else:
        # Stand-in for Workstream B - not part of the Part C deliverable
        from helpmate.adapters.s3_files import S3FileStore

        if not settings.s3_endpoint or not settings.s3_secret_key.get_secret_value():
            raise AdapterNotImplemented(
                "HELPMATE_FILES=s3 needs HELPMATE_S3_ENDPOINT and S3_ACCESS_KEY / S3_SECRET_KEY "
                "(the SeaweedFS container's credentials) in .env."
            )
        files = S3FileStore(
            settings.s3_endpoint,
            settings.s3_access_key,
            settings.s3_secret_key.get_secret_value(),
            settings.s3_bucket,
        )

    # --- Mail + calendar (B) ---
    mail: MailPort = FakeMail()
    calendar: CalendarPort = FakeCalendar()
    if settings.mail == "gmail" or settings.calendar == "google":
        # Stand-in for Workstream B - not part of the Part C deliverable
        from helpmate.adapters.gcal import GoogleCalendar
        from helpmate.adapters.gmail import GmailMail
        from helpmate.adapters.google_oauth import GoogleApi, GoogleCredentials

        google = GoogleApi(
            http_client("", httpx.Timeout(30.0, connect=5.0)),
            GoogleCredentials(settings.google_token_file),
        )
        if settings.mail == "gmail":
            mail = GmailMail(google)
        if settings.calendar == "google":
            calendar = GoogleCalendar(google, settings.tz)

    # --- Tools, policy engine, agent (A) ---
    tools = default_registry()
    deps = ToolDeps(
        repos,
        scheduler,
        clock,
        settings.tz,
        mail,
        calendar,
        (settings.day_start_hour, settings.day_end_hour),
    )
    policy = PolicyEngine(tools, deps)
    agent: AgentPort
    if settings.agent == "scripted":
        agent = ScriptedAgent(
            policy, llm, repos.memory, clock, settings.tz, settings.fake_stream_delay_seconds
        )
    else:
        # Stand-in for Workstream A - not part of the Part C deliverable
        from helpmate.agent.loop import LoopAgent
        from helpmate.memory.retrieval import MemoryRetriever

        recall = MemoryRetriever(
            repos.memory, embeddings, settings.memory_top_k, settings.memory_min_score
        )
        agent = LoopAgent(policy, llm, repos.memory, repos.chat, clock, settings.tz, recall)

    # --- Jobs beyond reminders (B) ---
    from helpmate.worker.checkin import EveningCheckIn
    from helpmate.worker.scheduler import JobScheduler

    if isinstance(scheduler, JobScheduler):  # dev and pg both are
        EveningCheckIn(scheduler, repos, calendar, notifier, clock, settings.tz).install()

    return Container(
        settings=settings,
        clock=clock,
        repos=repos,
        auth=auth,
        llm=llm,
        embeddings=embeddings,
        stt=stt,
        tts=tts,
        notifier=notifier,
        scheduler=scheduler,
        mail=mail,
        calendar=calendar,
        tools=tools,
        policy=policy,
        agent=agent,
        triage=Triage(mail, llm),
        files=files,
        library=DocumentLibrary(repos.documents, files, embeddings, llm),
        _http_clients=http_clients,
    )
