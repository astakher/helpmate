from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

from helpmate.domain.models import LLMChunk, LLMMessage, ToolSpec


class FakeLLM:
    """Streams a canned reply word by word (HELPMATE_LLM=fake)."""

    name = "fake"
    is_fake = True

    def __init__(self, stream_delay: float = 0.03) -> None:
        self._delay = stream_delay

    async def chat(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[ToolSpec] = (),
        json_schema: Mapping[str, Any] | None = None,
    ) -> AsyncIterator[LLMChunk]:
        if json_schema is not None:  # structured output: the smallest valid object
            yield LLMChunk(text=json.dumps(_minimal(json_schema)))
            yield LLMChunk(done=True, output_tokens=1)
            return
        last_user = next((m.content for m in reversed(messages) if m.role == "user"), "")
        reply = (
            f'(fake LLM) You said: "{last_user}". Set HELPMATE_LLM=ollama to talk to the real '
            "model. Try: remind me to call mom in 2 minutes."
        )
        pieces = re.findall(r"\S+\s*", reply)
        for piece in pieces:
            if self._delay:
                await asyncio.sleep(self._delay)
            yield LLMChunk(text=piece)
        yield LLMChunk(done=True, output_tokens=len(pieces))


def _minimal(schema: Mapping[str, Any]) -> Any:
    """First enum value / empty value for each required property (e.g. {"action": "reply"})."""
    if "enum" in schema:
        return schema["enum"][0]
    if schema.get("type") == "object":
        props = schema.get("properties", {})
        return {k: _minimal(props[k]) for k in schema.get("required", []) if k in props}
    return {"string": "", "integer": 0, "number": 0, "boolean": False, "array": []}.get(
        schema.get("type", ""), None
    )


class FakeEmbeddings:
    """Deterministic bag-of-hashed-words vectors: texts sharing words are similar, which is
    enough for retrieval tests without a model."""

    name = "fake"
    is_fake = True
    dimensions = 768

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dimensions
        for token in re.findall(r"\w+", text.lower()):
            digest = hashlib.sha256(token.encode()).digest()
            vec[int.from_bytes(digest[:4], "big") % self.dimensions] += 1.0
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]
