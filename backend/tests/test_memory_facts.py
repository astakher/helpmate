# Stand-in for Workstream A - not part of the Part C deliverable
"""PATCH /api/memory/facts/{id}: the Memory page's Edit button (docs/part-c.md §7)."""

from __future__ import annotations

from helpmate.domain.models import MemoryFact


async def _seed(container, clock) -> MemoryFact:
    fact = MemoryFact(
        id="f1", text="my advisor is Dr. Lee", source="chat:s1", created_at=clock.now()
    )
    await container.repos.memory.add_fact(fact)
    return fact


async def test_owner_can_edit_a_fact(client, container, clock):
    await _seed(container, clock)
    response = await client.patch("/api/memory/facts/f1", json={"text": "  my advisor is Dr. Li "})
    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "my advisor is Dr. Li" and body["source"] == "chat:s1"
    [fact] = (await client.get("/api/memory/facts")).json()
    assert fact["text"] == "my advisor is Dr. Li"


async def test_edit_rejects_empty_text_and_unknown_ids(client, container, clock):
    await _seed(container, clock)
    assert (await client.patch("/api/memory/facts/f1", json={"text": "   "})).status_code == 422
    assert (await client.patch("/api/memory/facts/f1", json={"text": ""})).status_code == 422
    assert (await client.patch("/api/memory/facts/nope", json={"text": "x"})).status_code == 404
