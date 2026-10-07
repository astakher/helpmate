# Stand-in for Workstream A - not part of the Part C deliverable
"""LoopAgent (HELPMATE_AGENT=loop): the model decides which tool to call.

A working stand-in for Workstream A's agent loop, built on the pipeline measured in
docs/benchmarks/llama-tool-calling-fixes.md ("routed"):

0. Follow-ups: when the chat has earlier turns, one structured call rewrites the owner's latest
   message into a request that stands on its own ("Amandeepgill163@gmail.com" after "Who should
   I send it to?" -> "Email the love poem for Bella to amandeepgill163@gmail.com";
   llm_tools.STANDALONE_PROMPT). Steps 1-2 use that request. The first message of a chat skips it.
1. Route: classify the request with NO tools attached, via structured output
   (reply | one of llm_tools.ROUTES' tools).
2. reply -> stream a plain answer (reply_prompt, the conversation so far, no tools). It can't
            claim a card it didn't make (llm_tools.ClaimFilter).
   send_email -> written like a reply first, so the owner sees it and the chat keeps it ("make
            it shorter", "send the poem you wrote"): code checks the owner said what to write
            (says_what_to_write), the writing step reads no addresses (for_writing) and its
            refusals and notes never reach the card (DraftFilter); then a small structured call
            gives recipients and subject, checked in code (llm_tools.resolve), and the card gets
            exactly the text shown.
   tool  -> call the model offering only that tool, with only that tool's rules (tool_prompt);
            turn the call into canonical args in code (llm_tools.resolve); if they're invalid,
            send the problem back once. NeedsOwner (e.g. no address) is asked back instead.
3. The canonical call goes through the PolicyEngine exactly like the ScriptedAgent's: read-only
   tools run, every write becomes a proposal card. Nothing is written without approval.

Prompt injection: emails and calendar entries never reach the model as instructions. Read-only
results go straight to the owner; the chat keeps only the assistant's one-line summary (an email
search's cards are stored apart), and every assistant turn given back to the model has sentences
aimed at an AI cut out (triage.quarantine). A recipient must appear in the owner's own messages
(or facts they saved), never in the assistant's text or an email, and every write still needs an
approved card that shows its full text.

"remember that ..." files a memory suggestion, as in the ScriptedAgent. Approved facts come back
through memory search (memory/retrieval.py): the few that match the message go into the reply or
tool prompt, the chat shows "From memory: …", and an email address from memory counts as given
by the owner. "What do you remember about me?" routes to list_memory.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from helpmate.agent import llm_tools
from helpmate.agent.policy import PolicyEngine
from helpmate.agent.triage import quarantine
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
from helpmate.memory.retrieval import MemoryRetriever, ScoredFact

# The conversation given back to the model, newest turns first, within a size budget (the context
# is 4,096 tokens). It was "the last 6 messages": a poem 11 messages back was forgotten (Oct 7).
HISTORY_CHARS = 6000
HISTORY_MAX = 20
_EXAMPLES = {  # shown when a request couldn't be turned into a tool call
    "create_reminder": "'remind me to call mom tomorrow at 5pm'",
    "create_task": "'add book the dentist to this term'",
    "list_events": "'what's on my calendar tomorrow'",
    "create_event": "'add lunch with Sam to my calendar Friday at 12:30'",
    "find_free_time": "'when am I free for an hour this week'",
    "search_email": "'any new emails from the school'",
    "send_email": "'email jo@example.com to say I'm running late'",
}
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
        recall: MemoryRetriever | None = None,
    ) -> None:
        self._policy = policy
        self._llm = llm
        self._memory = memory
        self._chat = chat
        self._clock = clock
        self._tz = tz
        self._recall = recall

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
        history, owner_said = await self._conversation(session_id, text)
        request = await self._standalone(history, text) if history else text
        # memory search (~30 ms) runs while the router decides, so it costs no extra time
        route, recalled = await asyncio.gather(self._route(request), self._relevant_facts(request))
        facts = [] if route == "list_memory" else [s.fact.text for s in recalled]
        if facts:  # show the owner what was used, so a stale fact is easy to spot and fix
            yield ToolResult(call_id=new_id(), ok=True, summary="From memory: " + "; ".join(facts))
        # what the owner themselves said in this chat, and facts they saved: the only places an
        # email address may come from
        said = "\n".join([text, *owner_said, *facts])

        if route == "reply":
            messages = [
                LLMMessage(role="system", content=llm_tools.reply_prompt(now, self._tz, facts)),
                *history,
                LLMMessage(role="user", content=text),
            ]
            # a plain reply makes no card: if the chat holds "Approve the card", the model may
            # copy it, so such sentences are dropped (only then: it costs a sentence of delay)
            claims = (
                llm_tools.ClaimFilter()
                if any(llm_tools.CARD_CLAIM.search(m.content) for m in history)
                else None
            )
            async for chunk in self._llm.chat(messages):
                if chunk.text and (shown := claims.feed(chunk.text) if claims else chunk.text):
                    first_token = first_token or time.perf_counter()
                    tokens += 1
                    yield MessageDelta(text=shown)
                if chunk.output_tokens:
                    tokens = chunk.output_tokens
            if claims and (rest := claims.finish()):
                first_token = first_token or time.perf_counter()
                yield MessageDelta(text=rest)
            yield MessageDone(message_id=new_id(), ttft_ms=_ms(started, first_token), tokens=tokens)
            return

        if route == "send_email":  # written as a reply first, then prepared as a card
            async for event in self._email(session_id, request, history, facts, said, now):
                if isinstance(event, MessageDelta):
                    first_token = first_token or time.perf_counter()
                    tokens += 1
                yield event
            yield MessageDone(message_id=new_id(), ttft_ms=_ms(started, first_token), tokens=tokens)
            return

        specs = [s for s in llm_tools.specs(self._policy.tools) if s.name == route]
        messages = [
            LLMMessage(role="system", content=llm_tools.tool_prompt(route, now, self._tz, facts)),
            LLMMessage(role="user", content=request),
        ]
        reply = await self._collect(messages, specs)
        if not reply.calls:  # routed to a tool, but the model answered in words instead
            async for event in say(reply.text.strip() or "Sorry, I didn't catch that."):
                yield event
            yield MessageDone(message_id=new_id(), ttft_ms=_ms(started, first_token), tokens=tokens)
            return

        call = reply.calls[0]
        args, error = self._resolve(call, now, said, request)
        if isinstance(error, llm_tools.NeedsOwner):  # only the owner can fix it: ask them
            yield ToolResult(call_id=call.id, ok=False, summary=f"{call.name}: needs your input")
            async for event in say(str(error)):
                yield event
            yield MessageDone(message_id=new_id(), ttft_ms=_ms(started, first_token), tokens=tokens)
            return
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
                args, error = self._resolve(call, now, said, request)

        if args is None:
            yield ToolResult(call_id=call.id, ok=False, summary=str(error or "invalid arguments"))
            async for event in say(
                str(error)
                if isinstance(error, llm_tools.NeedsOwner)
                else "Sorry, I couldn't work out the details. Could you rephrase it, for example "
                f"{_EXAMPLES.get(route, _EXAMPLES['create_reminder'])}?"
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
            if p.warnings:
                answer += " Heads up: " + "; ".join(p.warnings) + "."
        else:
            yield ToolResult(
                call_id=canonical.id, ok=outcome.ok, summary=outcome.summary, emails=outcome.emails
            )
            answer = outcome.summary
        async for event in say(answer):
            yield event
        yield MessageDone(message_id=new_id(), ttft_ms=_ms(started, first_token), tokens=tokens)

    async def _relevant_facts(self, text: str) -> list[ScoredFact]:
        return await self._recall.relevant(text) if self._recall is not None else []

    async def _route(self, text: str) -> str:
        routes = llm_tools.routes_for(text)  # e.g. no reminder routes without a "remind" word
        messages = [
            LLMMessage(role="system", content=llm_tools.router_prompt(routes)),
            LLMMessage(role="user", content=text),
        ]
        schema = llm_tools.route_format(routes)
        parts = [c.text async for c in self._llm.chat(messages, json_schema=schema)]
        return llm_tools.parse_route("".join(parts), routes)

    async def _collect(self, messages: Sequence[LLMMessage], specs: list[ToolSpec]) -> _Reply:
        reply = _Reply()
        async for chunk in self._llm.chat(messages, specs):
            reply.text += chunk.text
            reply.calls.extend(chunk.tool_calls)
            reply.output_tokens = chunk.output_tokens or reply.output_tokens
        if not reply.calls and len(specs) == 1:  # the call written out as text (llm_tools)
            arguments = llm_tools.text_call(reply.text, specs[0].name)
            if arguments is not None:
                reply.calls = [ToolCall(id=new_id(), name=specs[0].name, arguments=arguments)]
                reply.text = ""
        return reply

    def _resolve(
        self, call: ToolCall, now: datetime, said: str, asked: str
    ) -> tuple[dict[str, Any] | None, llm_tools.ResolveError | None]:
        try:
            args = llm_tools.resolve(
                call.name, call.arguments, self._policy.tools, now, self._tz, said, asked
            )
        except llm_tools.ResolveError as exc:
            return None, exc
        return args, None

    async def _email(
        self,
        session_id: str,
        request: str,
        history: list[LLMMessage],
        facts: list[str],
        said: str,
        now: datetime,
    ) -> AsyncIterator[ChatEvent]:
        """An email: write it as a reply the owner sees (and the chat keeps), then a small call
        picks recipients and subject, and the card gets exactly that text. Recipients are checked
        against the owner's own words (llm_tools.resolve), as for any send_email."""
        if not llm_tools.says_what_to_write(request):  # decided in code: never made-up text
            yield MessageDelta(text="What should the email say?")
            return
        # the writing step reads no email addresses: they made llama3.2 refuse (llm_tools)
        messages = [
            LLMMessage(role="system", content=llm_tools.compose_prompt(now, self._tz, facts)),
            *(LLMMessage(role=m.role, content=llm_tools.for_writing(m.content)) for m in history),
            LLMMessage(role="user", content=llm_tools.for_writing(request)),
        ]
        draft_text = llm_tools.DraftFilter()
        intro = False
        async for chunk in self._llm.chat(messages):
            if chunk.text and (shown := draft_text.feed(chunk.text)):
                if not intro:
                    intro = True
                    yield MessageDelta(text="Here's the draft:\n\n")
                yield MessageDelta(text=shown)
            if draft_text.refused:
                break
        if rest := draft_text.finish():
            if not intro:
                intro = True
                yield MessageDelta(text="Here's the draft:\n\n")
            yield MessageDelta(text=rest)
        body = draft_text.body.strip()
        if draft_text.refused or not body:
            yield MessageDelta(text="Sorry, I couldn't write that one. Could you ask again?")
            return
        subject_hint = draft_text.subject

        header = llm_tools.email_header_messages(request, body, facts)
        try:
            parts = [
                c.text
                async for c in self._llm.chat(header, json_schema=llm_tools.EMAIL_HEADER_FORMAT)
            ]
            to, subject = llm_tools.parse_email_header("".join(parts))
        except Exception:  # the owner's own address in the request is still found below
            to, subject = [], ""
        draft = {"to": to, "cc": [], "subject": subject or subject_hint or "Hello", "body": body}
        written_call = ToolCall(id=new_id(), name="send_email", arguments=draft)
        args, error = self._resolve(written_call, now, said, request)
        if args is None:
            yield MessageDelta(text=f"\n\n{error}")
            return
        call = ToolCall(id=new_id(), name="send_email", arguments=args)
        yield ToolStarted(call_id=call.id, tool=call.name, args=call.arguments)
        outcome = await self._policy.handle_call(call, session_id)
        if outcome.proposal is None:
            yield MessageDelta(text=f"\n\n{outcome.summary}")
            return
        yield ProposalCreated(proposal=outcome.proposal)
        recipients = ", ".join(args["to"])
        yield MessageDelta(
            text=f'\n\nI\'ve prepared it as an email to {recipients} ("{args["subject"]}"). '
            "Approve the card to send it."
        )

    async def _standalone(self, history: list[LLMMessage], text: str) -> str:
        """The latest message as a request that makes sense without the chat (step 0)."""
        messages = llm_tools.standalone_messages(history, text)
        schema = llm_tools.STANDALONE_FORMAT
        try:
            parts = [c.text async for c in self._llm.chat(messages, json_schema=schema)]
        except Exception:  # never let this step stop a reply: fall back to the message as typed
            return text
        return llm_tools.parse_standalone("".join(parts), text)

    async def _conversation(self, session_id: str, text: str) -> tuple[list[LLMMessage], list[str]]:
        """(the earlier turns to give the model, everything the owner said in this chat).

        Turns go newest first within HISTORY_CHARS, then back in order; the owner's own words
        verbatim, the assistant's with sentences aimed at an AI cut out (an email subject in a
        search summary can't steer the model). The chat route stores the current message before
        the agent runs, so it's dropped here (it's added as the final user message)."""
        stored = await self._chat.find_messages(session_id)
        if stored and stored[-1].role == Role.USER and stored[-1].text == text:
            stored = stored[:-1]
        turns: list[LLMMessage] = []
        used = 0
        for m in reversed(stored):
            if not m.text:
                continue
            content = m.text if m.role == Role.USER else quarantine(m.text)
            if turns and (used + len(content) > HISTORY_CHARS or len(turns) >= HISTORY_MAX):
                break
            role = "user" if m.role == Role.USER else "assistant"
            turns.append(LLMMessage(role=role, content=content))
            used += len(content)
        owner = [m.text for m in stored if m.role == Role.USER]
        return list(reversed(turns)), owner


def _ms(started: float, first_token: float | None) -> int | None:
    return int((first_token - started) * 1000) if first_token else None
