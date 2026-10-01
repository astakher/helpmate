# Stand-in for Workstream A - not part of the Part C deliverable
"""Memory search (memory/retrieval.py) and how the agent uses approved facts."""

from __future__ import annotations

from datetime import UTC, datetime

from test_loop_agent import ScriptLLM, agent_with, call, reply_text, run

from helpmate.adapters.fakes.fake_llm import FakeEmbeddings
from helpmate.adapters.fakes.memory_repos import InMemoryMemoryRepo
from helpmate.agent.loop import LoopAgent
from helpmate.domain.events import ProposalCreated, ToolResult
from helpmate.domain.models import MemoryFact
from helpmate.memory.retrieval import MemoryRetriever

NOW = datetime(2026, 10, 5, 16, 0, tzinfo=UTC)


def fact(fact_id: str, text: str) -> MemoryFact:
    return MemoryFact(id=fact_id, text=text, source="chat:s1", created_at=NOW)


class CountingEmbeddings(FakeEmbeddings):
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def embed(self, texts):
        self.texts.extend(texts)
        return await super().embed(texts)


class BrokenEmbeddings(FakeEmbeddings):
    async def embed(self, texts):
        raise ConnectionError("Ollama isn't running")


async def _memory(*facts: MemoryFact) -> InMemoryMemoryRepo:
    repo = InMemoryMemoryRepo()
    for f in facts:
        await repo.add_fact(f)
    return repo


async def test_finds_the_facts_that_match_and_nothing_for_unrelated_messages():
    memory = await _memory(
        fact("f1", "my advisor is Dr. Lee"),
        fact("f2", "my sister's birthday is March 3"),
        fact("f3", "I park in lot M"),
    )
    recall = MemoryRetriever(memory, FakeEmbeddings())
    assert [s.fact.id for s in await recall.relevant("who is my advisor?")] == ["f1"]
    assert await recall.relevant("what is 2 plus 2?") == []


async def test_facts_are_embedded_once_and_again_only_when_edited_or_deleted():
    memory = await _memory(fact("f1", "my advisor is Dr. Lee"), fact("f2", "I park in lot M"))
    embeddings = CountingEmbeddings()
    recall = MemoryRetriever(memory, embeddings)
    await recall.relevant("who is my advisor?")
    await recall.relevant("where do I park?")
    documents = [t for t in embeddings.texts if "advisor is" in t or "lot M" in t]
    assert len(documents) == 2  # each fact once, not once per question

    await memory.update_fact(fact("f1", "my advisor is Dr. Patel"))
    await memory.delete_fact("f2")
    [found] = await recall.relevant("who is my advisor?")
    assert found.fact.text == "my advisor is Dr. Patel"
    assert await recall.relevant("where do I park?") == []  # the deleted fact is gone


async def test_a_broken_embedding_model_means_no_memory_not_an_error():
    memory = await _memory(fact("f1", "my advisor is Dr. Lee"))
    assert await MemoryRetriever(memory, BrokenEmbeddings()).relevant("who is my advisor?") == []


async def _agent(container, llm, *facts: MemoryFact) -> LoopAgent:
    for f in facts:
        await container.repos.memory.add_fact(f)
    agent = agent_with(container, llm)
    # bag-of-words fakes score lower than a real model; 0.55 is tuned for nomic-embed-text
    agent._recall = MemoryRetriever(container.repos.memory, FakeEmbeddings(), min_score=0.3)
    return agent


async def test_replies_get_the_matching_facts_and_the_chat_says_so(container):
    llm = ScriptLLM(lambda text: "reply")
    agent = await _agent(
        container, llm, fact("f1", "my advisor is Dr. Lee"), fact("f2", "I park in lot M")
    )
    events = await run(agent, "who is my advisor?")
    [note] = [e for e in events if isinstance(e, ToolResult)]
    assert note.summary == "From memory: my advisor is Dr. Lee"
    system = llm.calls[1]["messages"][0].content  # [0] is the router
    assert "- my advisor is Dr. Lee" in system and "lot M" not in system
    assert "my advisor" not in llm.calls[0]["messages"][0].content  # routing never sees memory


async def test_an_email_address_from_memory_counts_as_given(container):
    llm = ScriptLLM(
        lambda text: "send_email",
        lambda messages: call(
            "send_email", to=["lee@mcmaster.ca"], subject="Meeting", body="Can we meet Friday?"
        ),
    )
    agent = await _agent(container, llm, fact("f1", "my advisor's email is lee@mcmaster.ca"))
    events = await run(agent, "email my advisor to ask about meeting Friday")
    [card] = [e.proposal for e in events if isinstance(e, ProposalCreated)]
    assert card.args["to"] == ["lee@mcmaster.ca"]
    assert "lee@mcmaster.ca" in llm.calls[1]["messages"][0].content  # the tool prompt had it


async def test_what_do_you_remember_lists_every_fact(container):
    llm = ScriptLLM(lambda text: "list_memory", lambda messages: call("list_memory"))
    agent = await _agent(
        container, llm, fact("f1", "my advisor is Dr. Lee"), fact("f2", "I park in lot M")
    )
    events = await run(agent, "what do you remember about me?")
    results = [e.summary for e in events if isinstance(e, ToolResult)]
    assert results == [
        "You asked me to remember 2 things:\n- my advisor is Dr. Lee\n- I park in lot M\n"
        "(Edit them on the Memory page.)"
    ]  # and no separate "From memory" note
    assert reply_text(events) == results[0]
