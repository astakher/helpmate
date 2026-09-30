# Stand-in for Workstream A - not part of the Part C deliverable
"""LoopAgent (HELPMATE_AGENT=loop): the model decides which tool to call.

A working stand-in for Workstream A's agent loop, built on the pipeline measured in
docs/benchmarks/llama-tool-calling-fixes.md ("routed"):

1. Route: classify the message with NO tools attached, via structured output
   (reply | create_reminder | create_task | list_reminders).
2. reply -> stream a plain answer (reply_prompt, recent chat history, no tools).
   tool  -> call the model offering only that tool; turn its call into canonical args in code
            (llm_tools.resolve); if they're invalid, send the problem back once.
3. The canonical call goes through the PolicyEngine exactly like the ScriptedAgent's: read-only
   tools run, every write becomes a proposal card. Nothing is written without approval.

"remember that ..." files a memory suggestion, as in the ScriptedAgent.
"""

from __future__ import annotations

import re
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from helpmate.agent import llm_tools
from helpmate.agent.policy import PolicyEngine
from helpmate.domain.events import (
    ChatEvent,
    MessageDelta,
    MessageDone,
    ProposalCreated,
    ToolResult,
    ToolStarted,
)
from helpmate.domain.models import (
    LLMMessage,
    MemorySuggestion,
    Role,
    Source,
    ToolCall,
    ToolSpec,
    new_id,
)
from helpmate.domain.ports import ChatRepo, Clock, LLMPort, MemoryRepo

HISTORY_MESSAGES = 6  # earlier turns given to plain replies (routing and tool calls are 1-turn)
_REMEMBER = re.compile(r"^(?:please )?remember(?: that)? (?P<fact>.{3,500})$", re.IGNORECASE)


@dataclass
class _Reply:
    """One model call's output, collected (tool calls) or streamed (text)."""

    text: str = ""
    calls: list[ToolCall] = field(default_factory=list)
    output_tokens: int | None = None


class LoopAgent:
    name = "loop"
    is_fake = False

    def __init__(
        self,
        policy: PolicyEngine,
        llm: LLMPort,
        memory: MemoryRepo,
        chat: ChatRepo,
        clock: Clock,
        tz: ZoneInfo,
    ) -> None:
        self._policy = policy
        self._llm = llm
        self._memory = memory
        self._chat = chat
        self._clock = clock
        self._tz = tz

    async def run(self, session_id: str, text: str, source: Source) -> AsyncIterator[ChatEvent]:
        started = time.perf_counter()
        first_token: float | None = None
        tokens = 0

        async def say(reply: str) -> AsyncIterator[ChatEvent]:
            nonlocal first_token, tokens
            for piece in re.findall(r"\S+\s*", reply):
                first_token = first_token or time.perf_counter()
                tokens += 1
                yield MessageDelta(text=piece)

        phrase = " ".join(text.split()).rstrip(".!")
        if match := _REMEMBER.match(phrase):
            suggestion = MemorySuggestion(
                id=new_id(),
                text=match["fact"],
                source=f"chat:{session_id}",
                created_at=self._clock.now(),
            )
            await self._memory.add_suggestion(suggestion)
            yield ToolResult(
                call_id=new_id(), ok=True, summary=f"Memory suggestion: {suggestion.text}"
            )
            async for event in say("I'll remember that once you approve it on the Memory page."):
                yield event
            yield MessageDone(message_id=new_id(), ttft_ms=_ms(started, first_token), tokens=tokens)
            return

        now = self._clock.now()
        route = await self._route(text)

        if route == "reply":
            messages = [
                LLMMessage(role="system", content=llm_tools.reply_prompt(now, self._tz)),
                *await self._history(session_id, text),
                LLMMessage(role="user", content=text),
            ]
            async for chunk in self._llm.chat(messages):
                if chunk.text:
                    first_token = first_token or time.perf_counter()
                    tokens += 1
                    yield MessageDelta(text=chunk.text)
                if chunk.output_tokens:
                    tokens = chunk.output_tokens
            yield MessageDone(message_id=new_id(), ttft_ms=_ms(started, first_token), tokens=tokens)
            return

        specs = [s for s in llm_tools.specs(self._policy.tools) if s.name == route]
        messages = [
            LLMMessage(role="system", content=llm_tools.system_prompt(now, self._tz)),
            LLMMessage(role="user", content=text),
        ]
        reply = await self._collect(messages, specs)
        if not reply.calls:  # routed to a tool, but the model answered in words instead
            async for event in say(reply.text.strip() or "Sorry, I didn't catch that."):
                yield event
            yield MessageDone(message_id=new_id(), ttft_ms=_ms(started, first_token), tokens=tokens)
            return

        call = reply.calls[0]
        args, error = self._resolve(call, now)
        if error is not None:  # validate-and-retry, once
            messages += [
                LLMMessage(role="assistant", content="", tool_calls=[call]),
                LLMMessage(
                    role="tool",
                    tool_name=call.name,
                    content=f"Error: {error} Call the tool again with corrected arguments.",
                ),
            ]
            retry = await self._collect(messages, specs)
            if retry.calls:
                call = retry.calls[0]
                args, error = self._resolve(call, now)

        if args is None:
            yield ToolResult(call_id=call.id, ok=False, summary=error or "invalid arguments")
            async for event in say(
                "Sorry, I couldn't work out the details. Could you rephrase it, for example "
                "'remind me to call mom tomorrow at 5pm'?"
            ):
                yield event
            yield MessageDone(message_id=new_id(), ttft_ms=_ms(started, first_token), tokens=tokens)
            return

        canonical = ToolCall(id=call.id, name=call.name, arguments=args)
        yield ToolStarted(call_id=canonical.id, tool=canonical.name, args=canonical.arguments)
        outcome = await self._policy.handle_call(canonical, session_id)
        if outcome.proposal is not None:
            yield ProposalCreated(proposal=outcome.proposal)
            p = outcome.proposal
            answer = f"I've prepared this: {p.title} ({p.summary}). Approve the card to go ahead."
        else:
            yield ToolResult(call_id=canonical.id, ok=outcome.ok, summary=outcome.summary)
            answer = outcome.summary
        async for event in say(answer):
            yield event
        yield MessageDone(message_id=new_id(), ttft_ms=_ms(started, first_token), tokens=tokens)

    async def _route(self, text: str) -> str:
        messages = [
            LLMMessage(role="system", content=llm_tools.ROUTER_PROMPT),
            LLMMessage(role="user", content=text),
        ]
        parts = [c.text async for c in self._llm.chat(messages, json_schema=llm_tools.ROUTE_FORMAT)]
        return llm_tools.parse_route("".join(parts))

    async def _collect(self, messages: Sequence[LLMMessage], specs: list[ToolSpec]) -> _Reply:
        reply = _Reply()
        async for chunk in self._llm.chat(messages, specs):
            reply.text += chunk.text
            reply.calls.extend(chunk.tool_calls)
            reply.output_tokens = chunk.output_tokens or reply.output_tokens
        return reply

    def _resolve(self, call: ToolCall, now: datetime) -> tuple[dict[str, Any] | None, str | None]:
        try:
            args = llm_tools.resolve(call.name, call.arguments, self._policy.tools, now, self._tz)
        except llm_tools.ResolveError as exc:
            return None, str(exc)
        return args, None

    async def _history(self, session_id: str, text: str) -> list[LLMMessage]:
        """Recent turns for plain replies. The chat route stores the current message before the
        agent runs, so it's dropped here (it's added as the final user message)."""
        stored = await self._chat.find_messages(session_id)
        if stored and stored[-1].role == Role.USER and stored[-1].text == text:
            stored = stored[:-1]
        return [
            LLMMessage(role="user" if m.role == Role.USER else "assistant", content=m.text)
            for m in stored[-HISTORY_MESSAGES:]
            if m.text
        ]


def _ms(started: float, first_token: float | None) -> int | None:
    return int((first_token - started) * 1000) if first_token else None
