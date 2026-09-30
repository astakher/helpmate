# Stand-in for Workstream A - not part of the Part C deliverable
"""LoopAgent (HELPMATE_AGENT=loop): routing, resolution, retry and the approval invariant."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from helpmate.adapters.clock import FakeClock
from helpmate.agent import llm_tools
from helpmate.agent.loop import LoopAgent
from helpmate.container import build_container
from helpmate.domain.events import MessageDelta, ProposalCreated, ToolResult, ToolStarted
from helpmate.domain.models import (
    ChatMessage,
    ChatSession,
    LLMChunk,
    LLMMessage,
    Role,
    ToolCall,
    ToolSpec,
    new_id,
)
from helpmate.settings import Settings

TZ = ZoneInfo("America/Toronto")
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=TZ)  # Monday noon


class ScriptLLM:
    """A test double for LLMPort. route_for(text) answers the routing call; act(messages) answers
    the tool call with a ToolCall or text; plain replies stream "Sure thing." Records every call."""

    name = "script"
    is_fake = True

    def __init__(self, route_for: Callable[[str], str], act=None) -> None:
        self.route_for = route_for
        self.act = act or (lambda messages: "Okay.")
        self.calls: list[dict[str, Any]] = []

    async def chat(
        self,
        messages: Sequence[LLMMessage],
        tools: Sequence[ToolSpec] = (),
        json_schema: Mapping[str, Any] | None = None,
    ) -> AsyncIterator[LLMChunk]:
        self.calls.append({"messages": list(messages), "tools": list(tools), "schema": json_schema})
        if json_schema is not None:
            yield LLMChunk(text=f'{{"action": "{self.route_for(messages[-1].content)}"}}')
        elif tools:
            out = self.act(list(messages))
            yield LLMChunk(tool_calls=[out]) if isinstance(out, ToolCall) else LLMChunk(text=out)
        else:
            for piece in ("Sure ", "thing."):
                yield LLMChunk(text=piece)
        yield LLMChunk(done=True, output_tokens=2)


def call(name: str, **arguments: Any) -> ToolCall:
    return ToolCall(id=new_id(), name=name, arguments=arguments)


@pytest.fixture
def container():
    settings = Settings(_env_file=None, scheduler_autostart=False)
    return build_container(settings, clock=FakeClock(NOW))


def agent_with(container, llm: ScriptLLM) -> LoopAgent:
    return LoopAgent(
        container.policy, llm, container.repos.memory, container.repos.chat, container.clock, TZ
    )


async def run(agent: LoopAgent, text: str, session_id: str = "s1") -> list:
    return [event async for event in agent.run(session_id, text, "text")]


def reply_text(events: list) -> str:
    return "".join(e.text for e in events if isinstance(e, MessageDelta))


async def test_reminder_becomes_a_card_with_the_time_worked_out_in_code(container):
    llm = ScriptLLM(
        lambda text: "create_reminder",
        lambda messages: call("create_reminder", text="call mom", when="in 10 minutes"),
    )
    events = await run(agent_with(container, llm), "remind me to call mom in 10 minutes")

    started = next(e for e in events if isinstance(e, ToolStarted))
    assert started.args["due_at"] == (NOW + timedelta(minutes=10)).isoformat()
    proposal = next(e for e in events if isinstance(e, ProposalCreated)).proposal
    assert proposal.title == "Reminder: call mom" and proposal.status == "pending"
    assert "Approve the card" in reply_text(events) and events[-1].type == "message.done"

    # only the routed tool was offered, and nothing was written before approval
    assert [s.name for s in llm.calls[1]["tools"]] == ["create_reminder"]
    assert await container.repos.reminders.find() == []
    await container.policy.decide(proposal.id, "approve")
    [reminder] = await container.repos.reminders.find()
    assert reminder.text == "call mom"


async def test_small_talk_gets_a_plain_reply_with_no_tools_offered(container):
    llm = ScriptLLM(lambda text: "reply")
    events = await run(agent_with(container, llm), "thanks, you're great")

    assert reply_text(events) == "Sure thing." and events[-1].ttft_ms is not None
    assert not any(isinstance(e, (ToolStarted, ProposalCreated)) for e in events)
    # 1: routing, structured output (no reminder routes: the message never says "remind")
    routes = llm_tools.routes_for("thanks, you're great")
    assert llm.calls[0]["schema"] == llm_tools.route_format(routes)
    reply_call = llm.calls[1]  # 2: the reply, no tools and the example-free prompt
    assert reply_call["tools"] == [] and "Examples" not in reply_call["messages"][0].content


async def test_list_reminders_runs_immediately(container):
    llm = ScriptLLM(lambda text: "list_reminders", lambda messages: call("list_reminders"))
    events = await run(agent_with(container, llm), "any reminders coming up?")
    result = next(e for e in events if isinstance(e, ToolResult))
    assert result.ok and reply_text(events) == result.summary


async def test_invalid_call_is_sent_back_once_and_fixed(container):
    def act(messages: list[LLMMessage]):
        if messages[-1].role == "tool":  # the retry: the error names working formats
            assert "in 10 minutes" in messages[-1].content
            return call("create_reminder", text="stretch", when="in 2 hours")
        return call("create_reminder", text="stretch", when="PT2H")

    llm = ScriptLLM(lambda text: "create_reminder", act)
    events = await run(agent_with(container, llm), "in two hours remind me to stretch")
    started = next(e for e in events if isinstance(e, ToolStarted))
    assert started.args["due_at"] == (NOW + timedelta(hours=2)).isoformat()
    assert any(isinstance(e, ProposalCreated) for e in events)


async def test_still_invalid_after_retry_asks_to_rephrase(container):
    llm = ScriptLLM(
        lambda text: "create_reminder",
        lambda messages: call("create_reminder", text="x", when="whenever"),
    )
    events = await run(agent_with(container, llm), "remind me whenever")
    result = next(e for e in events if isinstance(e, ToolResult))
    assert not result.ok and "rephrase" in reply_text(events)
    assert not any(isinstance(e, ProposalCreated) for e in events)
    assert await container.repos.proposals.find() == []


async def test_model_answering_in_words_after_routing_is_passed_through(container):
    llm = ScriptLLM(lambda text: "create_task", lambda messages: "What should the task be?")
    events = await run(agent_with(container, llm), "add a task")
    assert reply_text(events) == "What should the task be?"


async def test_remember_that_files_a_memory_suggestion(container):
    llm = ScriptLLM(lambda text: pytest.fail("no model call needed"))
    events = await run(agent_with(container, llm), "remember that my sister is Priya")
    [suggestion] = await container.repos.memory.find_suggestions()
    assert suggestion.text == "my sister is Priya" and "Memory page" in reply_text(events)


async def test_plain_replies_see_recent_history(container):
    repo = container.repos.chat
    await repo.add_session(ChatSession(id="s1", title=None, created_at=NOW))
    turns = [
        ("user", "my name is Aman"),
        ("assistant", "Hi Aman!"),
        ("user", "what's my name?"),  # stored by the chat route before the agent runs
    ]
    for role, text in turns:
        await repo.add_message(
            ChatMessage(id=new_id(), session_id="s1", role=Role(role), text=text, created_at=NOW)
        )
    llm = ScriptLLM(lambda text: "reply")
    await run(agent_with(container, llm), "what's my name?")
    sent = [(m.role, m.content) for m in llm.calls[1]["messages"][1:]]
    assert sent == turns  # history once, then the current message once


async def test_loop_agent_through_the_api_with_the_fake_llm(clock, parse_sse):
    """Wiring check: HELPMATE_AGENT=loop + HELPMATE_LLM=fake streams a reply over SSE."""
    import httpx

    from helpmate.main import create_app

    settings = Settings(
        _env_file=None, agent="loop", scheduler_autostart=False, fake_stream_delay_seconds=0
    )
    app = create_app(settings, clock=clock)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            health = (await client.get("/api/health")).json()
            assert health["adapters"]["agent"] == {"name": "loop", "fake": False}
            sid = (await client.post("/api/chat/sessions", json={})).json()["id"]
            response = await client.post(
                f"/api/chat/sessions/{sid}/messages", json={"text": "hello"}
            )
            events = parse_sse(response.text)
    assert [e["type"] for e in events][-1] == "message.done"
    assert "(fake LLM)" in "".join(e["text"] for e in events if e["type"] == "message.delta")
