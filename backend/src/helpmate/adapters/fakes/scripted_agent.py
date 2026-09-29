"""ScriptedAgent (HELPMATE_AGENT=scripted): the stand-in for Workstream A's agent loop.

Recognised phrases (see intent_parser) become tool calls that go through the real policy engine,
so approval cards, the audit log and reminders all work. Anything else is passed to the LLMPort,
which is the fake LLM or Ollama, so the real model can be tried before the agent loop exists.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import AsyncIterator
from zoneinfo import ZoneInfo

from helpmate.adapters.fakes.intent_parser import parse_intent
from helpmate.agent.policy import PolicyEngine
from helpmate.domain.events import (
    ChatEvent,
    MessageDelta,
    MessageDone,
    ProposalCreated,
    ToolResult,
    ToolStarted,
)
from helpmate.domain.models import LLMMessage, Source, new_id
from helpmate.domain.ports import Clock, LLMPort

SYSTEM_PROMPT = (
    "You are HelpMate, a concise personal assistant running entirely on the owner's laptop. "
    "Answer in at most three sentences. You cannot take actions yet; if asked to, say the "
    "owner can try phrases like 'remind me to call mom at 5pm' or 'add task read chapter 3'."
)


class ScriptedAgent:
    name = "scripted"
    is_fake = True

    def __init__(
        self, policy: PolicyEngine, llm: LLMPort, clock: Clock, tz: ZoneInfo, stream_delay: float
    ) -> None:
        self._policy = policy
        self._llm = llm
        self._clock = clock
        self._tz = tz
        self._delay = stream_delay

    async def run(self, session_id: str, text: str, source: Source) -> AsyncIterator[ChatEvent]:
        started = time.perf_counter()
        first_token: float | None = None
        tokens = 0

        call = parse_intent(text, self._clock.now(), self._tz)
        if call is not None:
            yield ToolStarted(call_id=call.id, tool=call.name, args=call.arguments)
            outcome = await self._policy.handle_call(call, session_id)
            if outcome.proposal is not None:
                yield ProposalCreated(proposal=outcome.proposal)
                p = outcome.proposal
                reply = (
                    f"I've prepared this: {p.title} ({p.summary}). Approve the card to go ahead."
                )
            else:
                yield ToolResult(call_id=call.id, ok=outcome.ok, summary=outcome.summary)
                reply = outcome.summary
            for piece in re.findall(r"\S+\s*", reply):
                if self._delay:
                    await asyncio.sleep(self._delay)
                first_token = first_token or time.perf_counter()
                tokens += 1
                yield MessageDelta(text=piece)
        else:
            messages = [
                LLMMessage(role="system", content=SYSTEM_PROMPT),
                LLMMessage(role="user", content=text),
            ]
            async for chunk in self._llm.chat(messages):
                if chunk.text:
                    first_token = first_token or time.perf_counter()
                    tokens += 1
                    yield MessageDelta(text=chunk.text)
                if chunk.output_tokens:
                    tokens = chunk.output_tokens

        ttft_ms = int((first_token - started) * 1000) if first_token else None
        yield MessageDone(message_id=new_id(), ttft_ms=ttft_ms, tokens=tokens)
