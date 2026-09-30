"""Real adapters against mocked HTTP: no Ollama needed. (Part C's speech adapters are tested in
test_speech_http.py, so Part C's tests can move to the shared repo on their own.)"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from helpmate.adapters.ollama_llm import OllamaLLM, OllamaUnavailable
from helpmate.api.sse import sse_stream
from helpmate.domain.events import MessageDelta
from helpmate.domain.models import LLMMessage, ToolSpec


def _ndjson(*objects: dict) -> bytes:
    return b"\n".join(json.dumps(o).encode() for o in objects) + b"\n"


async def test_ollama_streams_text_and_tool_calls():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            content=_ndjson(
                {"message": {"role": "assistant", "content": "Hel"}, "done": False},
                {"message": {"role": "assistant", "content": "lo"}, "done": False},
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {"function": {"name": "create_task", "arguments": {"title": "x"}}}
                        ],
                    },
                    "done": True,
                    "prompt_eval_count": 12,
                    "eval_count": 3,
                },
            ),
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://ollama")
    llm = OllamaLLM(client, "llama3.2:3b", think=False)
    tool = ToolSpec(name="create_task", description="d", parameters={"type": "object"})
    chunks = [c async for c in llm.chat([LLMMessage(role="user", content="hi")], [tool])]

    assert "".join(c.text for c in chunks) == "Hello"
    assert chunks[-1].tool_calls[0].name == "create_task"
    assert chunks[-1].output_tokens == 3
    assert seen["model"] == "llama3.2:3b" and seen["stream"] is True and seen["think"] is False
    assert seen["tools"][0]["function"]["name"] == "create_task"
    assert llm.name == "ollama:llama3.2:3b" and not llm.is_fake


async def test_ollama_structured_output_sends_format():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, content=_ndjson({"message": {"content": "{}"}, "done": True}))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://ollama")
    schema = {"type": "object", "properties": {"action": {"enum": ["reply"]}}}
    messages = [LLMMessage(role="user", content="hi")]
    chunks = [c async for c in OllamaLLM(client, "m").chat(messages, json_schema=schema)]
    assert seen["format"] == schema and "tools" not in seen and chunks[-1].done


async def test_ollama_down_gives_a_helpful_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://ollama")
    with pytest.raises(OllamaUnavailable, match="Is it running"):
        async for _ in OllamaLLM(client, "m").chat([LLMMessage(role="user", content="hi")]):
            pass


async def test_sse_heartbeat_and_error_frames():
    async def slow_then_fail():
        await asyncio.sleep(0.05)
        yield MessageDelta(text="hi")
        raise RuntimeError("model crashed")

    frames = [f async for f in sse_stream(slow_then_fail(), ping_seconds=0.01)]
    assert frames[0] == ": ping\n\n"
    assert any(f.startswith("event: message.delta") for f in frames)
    assert frames[-1].startswith("event: error") and "model crashed" in frames[-1]
