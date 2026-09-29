"""Server-sent events encoding with heartbeats.

The web app POSTs a message and reads the response body as a stream (fetch + ReadableStream;
EventSource can't POST). A `: ping` comment every 15 s keeps proxies such as Tailscale from
closing an idle stream while the model is thinking.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from helpmate.domain.events import ChatEvent, ErrorEvent

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}

_DONE = object()


def encode(event: ChatEvent) -> str:
    return f"event: {event.type}\ndata: {event.model_dump_json()}\n\n"


async def sse_stream(
    events: AsyncIterator[ChatEvent], ping_seconds: float = 15.0
) -> AsyncIterator[str]:
    queue: asyncio.Queue[object] = asyncio.Queue()

    async def pump() -> None:
        try:
            async for event in events:
                await queue.put(event)
        except Exception as exc:  # surface agent/LLM failures to the UI instead of a dead stream
            await queue.put(ErrorEvent(code="agent_error", message=str(exc)))
        finally:
            await queue.put(_DONE)

    task = asyncio.create_task(pump())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=ping_seconds)
            except TimeoutError:
                yield ": ping\n\n"
                continue
            if item is _DONE:
                break
            yield encode(item)  # type: ignore[arg-type]
    finally:
        task.cancel()
