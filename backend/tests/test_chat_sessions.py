# Stand-in for Workstream A - not part of the Part C deliverable
"""The chat list: titles from the first message, most recent activity first, delete."""

from __future__ import annotations

from datetime import timedelta

from helpmate.api.routes.chat import chat_title
from helpmate.domain.models import ChatMessage, ChatSession, Role


async def _chat(client, text: str) -> str:
    session_id = (await client.post("/api/chat/sessions", json={})).json()["id"]
    response = await client.post(
        f"/api/chat/sessions/{session_id}/messages", json={"text": text, "source": "text"}
    )
    assert response.status_code == 200
    return session_id


async def test_chats_are_titled_by_their_first_message_and_listed_newest_activity_first(
    client, clock
):
    first = await _chat(client, "remind me to stretch in 1 minute")
    clock.advance(minutes=1)
    second = await _chat(client, "what are my reminders?")
    listed = (await client.get("/api/chat/sessions")).json()
    assert [(s["id"], s["title"]) for s in listed] == [
        (second, "what are my reminders?"),
        (first, "remind me to stretch in 1 minute"),
    ]

    clock.advance(minutes=1)  # carrying on in the older chat moves it to the top...
    await client.post(
        f"/api/chat/sessions/{first}/messages", json={"text": "thanks", "source": "text"}
    )
    listed = (await client.get("/api/chat/sessions")).json()
    assert [s["id"] for s in listed] == [first, second]
    assert listed[0]["title"] == "remind me to stretch in 1 minute"  # ...and keeps its title


async def test_empty_chats_are_not_listed(client):
    await client.post("/api/chat/sessions", json={})
    assert (await client.get("/api/chat/sessions")).json() == []


async def test_untitled_chats_from_before_titles_get_one(client, container, clock):
    await container.repos.chat.add_session(ChatSession(id="old", created_at=clock.now()))
    await container.repos.chat.add_message(
        ChatMessage(
            id="m1",
            session_id="old",
            role=Role.USER,
            text="add task read chapter 3",
            created_at=clock.now() + timedelta(seconds=1),
        )
    )
    [listed] = (await client.get("/api/chat/sessions")).json()
    assert listed["title"] == "add task read chapter 3"
    assert (await container.repos.chat.get_session("old")).title == "add task read chapter 3"


async def test_deleting_a_chat_removes_it_and_its_messages(client, container):
    keep = await _chat(client, "hello")
    gone = await _chat(client, "remind me to stretch in 1 minute")
    assert (await client.delete(f"/api/chat/sessions/{gone}")).status_code == 204
    assert [s["id"] for s in (await client.get("/api/chat/sessions")).json()] == [keep]
    assert (await client.get(f"/api/chat/sessions/{gone}/messages")).status_code == 404
    assert await container.repos.chat.find_messages(gone) == []
    assert (await client.delete(f"/api/chat/sessions/{gone}")).status_code == 404
    # the approval card it made is still on the Approvals page
    assert [p["session_id"] for p in (await client.get("/api/proposals")).json()] == [gone]


def test_long_first_messages_are_cut_at_a_word():
    title = chat_title(
        "please  remind me tomorrow morning at nine to email the landlord about the leak"
    )
    assert title == "please remind me tomorrow morning at nine to email the…"
    assert len(title) <= 61
