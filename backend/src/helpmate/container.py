"""Composition root: the one place that turns settings into concrete adapters.

To plug in a real adapter, replace the matching `_not_yet(...)` branch below with it, then flip
the HELPMATE_* variable in .env. Nothing else in the codebase changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import NoReturn

import httpx

from helpmate.adapters.clock import SystemClock
from helpmate.adapters.fakes.dev_auth import DevAuth
from helpmate.adapters.fakes.dev_scheduler import DevScheduler
from helpmate.adapters.fakes.fake_llm import FakeEmbeddings, FakeLLM
from helpmate.adapters.fakes.fake_speech import FakeSTT, FakeTTS
from helpmate.adapters.fakes.log_notifier import LogNotifier
from helpmate.adapters.fakes.memory_repos import InMemoryRepositories
from helpmate.adapters.fakes.scripted_agent import ScriptedAgent
from helpmate.adapters.speech_http import HttpSTT, HttpTTS
from helpmate.agent.policy import PolicyEngine
from helpmate.agent.tools import ToolDeps, ToolRegistry, default_registry
from helpmate.domain.ports import (
    Adapter,
    AgentPort,
    AuthPort,
    Clock,
    EmbeddingPort,
    LLMPort,
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
    tools: ToolRegistry
    policy: PolicyEngine
    agent: AgentPort
    _http_clients: list[httpx.AsyncClient] = field(default_factory=list)

    def adapters(self) -> dict[str, Adapter]:
        return {
            "agent": self.agent,
            "llm": self.llm,
            "embeddings": self.embeddings,
            "repo": self.repos,
            "scheduler": self.scheduler,
            "auth": self.auth,
            "notifier": self.notifier,
            "stt": self.stt,
            "tts": self.tts,
        }

    async def startup(self) -> None:
        if isinstance(self.repos, InMemoryRepositories):
            await self.repos.seed(self.clock.now(), self.settings.timezone)
        if self.settings.scheduler_autostart:
            await self.scheduler.start()

    async def shutdown(self) -> None:
        await self.scheduler.stop()
        for client in self._http_clients:
            await client.aclose()


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
        _not_yet("repo", settings.repo)

    # --- Auth (B) ---
    auth: AuthPort
    if settings.auth == "dev":
        auth = DevAuth()
    else:
        _not_yet("auth", settings.auth)

    # --- Notifications (C) ---
    notifier: NotifierPort
    if settings.notifier == "log":
        notifier = LogNotifier()
    else:
        _not_yet("notifier", settings.notifier)

    # --- Scheduler (B) ---
    scheduler: SchedulerPort
    if settings.scheduler == "dev":
        scheduler = DevScheduler(repos, notifier, clock, settings.scheduler_tick_seconds)
    else:
        _not_yet("scheduler", settings.scheduler)

    # --- LLM + embeddings (A) ---
    llm: LLMPort
    embeddings: EmbeddingPort
    if settings.llm == "fake":
        llm = FakeLLM(settings.fake_stream_delay_seconds)
        embeddings = FakeEmbeddings()
    else:
        from helpmate.adapters.ollama_llm import OllamaEmbeddings, OllamaLLM

        ollama = http_client(settings.ollama_url, httpx.Timeout(120.0, connect=5.0))
        llm = OllamaLLM(ollama, settings.ollama_model, think=settings.ollama_think)
        embeddings = OllamaEmbeddings(ollama, settings.ollama_embed_model)

    # --- Speech (C) ---
    stt: STTPort = FakeSTT(settings.fake_transcript)
    tts: TTSPort = FakeTTS()
    if "http" in (settings.stt, settings.tts):
        speech = http_client(settings.speech_url, httpx.Timeout(60.0, connect=3.0))
        if settings.stt == "http":
            stt = HttpSTT(speech)
        if settings.tts == "http":
            tts = HttpTTS(speech)

    # --- Tools, policy engine, agent (A) ---
    tools = default_registry()
    policy = PolicyEngine(tools, ToolDeps(repos, scheduler, clock, settings.tz))
    agent: AgentPort
    if settings.agent == "scripted":
        agent = ScriptedAgent(
            policy, llm, repos.memory, clock, settings.tz, settings.fake_stream_delay_seconds
        )
    else:
        _not_yet("agent", settings.agent)

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
        tools=tools,
        policy=policy,
        agent=agent,
        _http_clients=http_clients,
    )
