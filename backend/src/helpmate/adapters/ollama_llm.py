"""Ollama adapters (HELPMATE_LLM=ollama). Minimal week-1 version; Workstream A owns and extends it.

Uses Ollama's native API: POST /api/chat streams NDJSON, and POST /api/embed returns embeddings.
Ollama must listen on 127.0.0.1 only (OLLAMA_HOST), never on the network.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from helpmate.domain.models import LLMChunk, LLMMessage, ToolCall, ToolSpec, new_id


class OllamaUnavailable(RuntimeError):
    pass


class OllamaLLM:
    is_fake = False

    def __init__(
        self,
        client: httpx.AsyncClient,
        model: str,
        think: bool | None = None,
        options: dict[str, Any] | None = None,
    ) -> None:
        self._client = client
        self._model = model
        self._think = think
        self._options = options or {}
        self.name = f"ollama:{model}"

    async def chat(
        self, messages: Sequence[LLMMessage], tools: Sequence[ToolSpec] = ()
    ) -> AsyncIterator[LLMChunk]:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [_to_ollama_message(m) for m in messages],
            "stream": True,
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]
        if self._think is not None:
            payload["think"] = self._think
        if self._options:
            payload["options"] = self._options

        try:
            async with self._client.stream("POST", "/api/chat", json=payload) as response:
                if response.status_code != 200:
                    body = (await response.aread()).decode(errors="replace")
                    raise OllamaUnavailable(f"Ollama returned {response.status_code}: {body}")
                async for line in response.aiter_lines():
                    if line.strip():
                        yield _parse_chunk(json.loads(line))
        except httpx.ConnectError as exc:
            raise OllamaUnavailable(
                f"Cannot reach Ollama at {self._client.base_url}. Is it running? "
                "(check the tray icon, or run `ollama ps`)"
            ) from exc


class OllamaEmbeddings:
    is_fake = False

    def __init__(self, client: httpx.AsyncClient, model: str, dimensions: int = 768) -> None:
        self._client = client
        self._model = model
        self.dimensions = dimensions
        self.name = f"ollama:{model}"

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        response = await self._client.post(
            "/api/embed", json={"model": self._model, "input": list(texts)}
        )
        response.raise_for_status()
        return response.json()["embeddings"]


def _to_ollama_message(message: LLMMessage) -> dict[str, Any]:
    out: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.tool_calls:
        out["tool_calls"] = [
            {"function": {"name": c.name, "arguments": c.arguments}} for c in message.tool_calls
        ]
    if message.tool_name:
        out["tool_name"] = message.tool_name
    return out


def _parse_chunk(data: dict[str, Any]) -> LLMChunk:
    message = data.get("message") or {}
    calls = [
        ToolCall(
            id=new_id(),
            name=c["function"]["name"],
            arguments=c["function"].get("arguments") or {},
        )
        for c in message.get("tool_calls") or []
    ]
    return LLMChunk(
        text=message.get("content") or "",
        tool_calls=calls,
        done=bool(data.get("done")),
        prompt_tokens=data.get("prompt_eval_count"),
        output_tokens=data.get("eval_count"),
    )
