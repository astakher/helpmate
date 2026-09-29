"""FastAPI app factory and the `helpmate-api` entry point."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.staticfiles import StaticFiles
from pydantic import TypeAdapter
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.types import Scope

from helpmate import __version__
from helpmate.api import api_router
from helpmate.container import build_container
from helpmate.domain.events import ChatEvent
from helpmate.domain.ports import Clock
from helpmate.settings import Settings

log = logging.getLogger("helpmate")


def create_app(settings: Settings | None = None, clock: Clock | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        container = build_container(settings, clock=clock)
        app.state.container = container
        await container.startup()
        summary = ", ".join(
            f"{seam}={a.name}{' (fake)' if a.is_fake else ''}"
            for seam, a in container.adapters().items()
        )
        log.info("HelpMate %s up: %s", __version__, summary)
        try:
            yield
        finally:
            await container.shutdown()

    app = FastAPI(
        title="HelpMate API",
        version=__version__,
        lifespan=lifespan,
        separate_input_output_schemas=False,
    )
    app.include_router(api_router)
    app.openapi = lambda: _openapi_with_events(app)  # type: ignore[method-assign]

    if settings.serve_web:
        if not (settings.web_dist / "index.html").exists():
            raise RuntimeError(f"HELPMATE_SERVE_WEB=1 but {settings.web_dist} has no build")
        app.mount("/", SPAStaticFiles(directory=settings.web_dist, html=True), name="web")
    return app


def _openapi_with_events(app: FastAPI) -> dict[str, Any]:
    """OpenAPI can't describe SSE frames, so publish the ChatEvent union as a named component."""
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
    event_schema = TypeAdapter(ChatEvent).json_schema(ref_template="#/components/schemas/{model}")
    components = schema.setdefault("components", {}).setdefault("schemas", {})
    for name, definition in event_schema.pop("$defs", {}).items():
        components.setdefault(name, definition)
    components["ChatEvent"] = event_schema
    app.openapi_schema = schema
    return schema


class SPAStaticFiles(StaticFiles):
    """Serves the built web app; unknown paths fall back to index.html for client-side routes."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            # scope["path"], not `path`: StaticFiles normalises `path` with OS separators
            if exc.status_code != 404 or scope["path"].startswith("/api/"):
                raise
            return await super().get_response("index.html", scope)


def run() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    settings = Settings()
    uvicorn.run(
        "helpmate.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
    )
