from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import FastAPI

from helpmate.adapters.clock import FakeClock
from helpmate.container import Container
from helpmate.main import create_app
from helpmate.settings import Settings

TORONTO = ZoneInfo("America/Toronto")


@pytest.fixture
def clock() -> FakeClock:
    # Monday noon, Toronto (EDT)
    return FakeClock(datetime(2026, 10, 5, 12, 0, tzinfo=TORONTO))


@pytest.fixture
def settings() -> Settings:
    # _env_file=None: tests never read a developer's .env
    return Settings(_env_file=None, scheduler_autostart=False, fake_stream_delay_seconds=0)


@pytest.fixture
async def app(settings: Settings, clock: FakeClock) -> AsyncIterator[FastAPI]:
    application = create_app(settings, clock=clock)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
def container(app: FastAPI) -> Container:
    return app.state.container


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _parse_sse(body: str) -> list[dict[str, Any]]:
    events = []
    for frame in body.split("\n\n"):
        data = [line[5:].strip() for line in frame.splitlines() if line.startswith("data:")]
        if data:
            events.append(json.loads("".join(data)))
    return events


@pytest.fixture
def parse_sse() -> Callable[[str], list[dict[str, Any]]]:
    return _parse_sse
