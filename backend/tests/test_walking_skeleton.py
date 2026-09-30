"""The week-1 checkpoint, as a test: chat -> approval card -> approve -> reminder fires."""

from __future__ import annotations

from helpmate.adapters.fakes.log_notifier import LogNotifier


async def test_health_reports_every_seam_as_fake(client):
    body = (await client.get("/api/health")).json()
    assert body["status"] == "ok"
    assert set(body["adapters"]) == {
        "agent",
        "llm",
        "embeddings",
        "repo",
        "scheduler",
        "auth",
        "mail",
        "calendar",
        "notifier",
        "stt",
        "tts",
    }
    assert all(a["fake"] for a in body["adapters"].values())


async def test_reminder_round_trip(client, container, clock, parse_sse):
    session = (await client.post("/api/chat/sessions", json={})).json()

    response = await client.post(
        f"/api/chat/sessions/{session['id']}/messages",
        json={"text": "remind me to call mom in 1 minute", "source": "text"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    types = [e["type"] for e in events]
    assert types[0] == "tool.started"
    assert "proposal.created" in types
    assert "message.delta" in types
    assert types[-1] == "message.done"

    proposal = next(e for e in events if e["type"] == "proposal.created")["proposal"]
    assert proposal["status"] == "pending"
    assert proposal["tool"] == "create_reminder"

    # Nothing happens until the owner approves.
    assert (await client.get("/api/reminders")).json() == []

    decided = await client.post(
        f"/api/proposals/{proposal['id']}/decision", json={"decision": "approve"}
    )
    assert decided.json()["status"] == "executed"
    reminders = (await client.get("/api/reminders")).json()
    assert [r["text"] for r in reminders] == ["call mom"]

    # Not due yet, then due after the clock moves past it.
    assert await container.scheduler.tick() == 0
    clock.advance(seconds=61)
    assert await container.scheduler.tick() == 1
    notifier = container.notifier
    assert isinstance(notifier, LogNotifier)
    assert notifier.sent[-1].body == "call mom"
    assert (await client.get("/api/reminders")).json()[0]["status"] == "sent"

    # Chat history and the audit trail were recorded.
    messages = (await client.get(f"/api/chat/sessions/{session['id']}/messages")).json()
    assert [m["role"] for m in messages] == ["user", "assistant"]
    actions = {a["action"] for a in (await client.get("/api/audit")).json()}
    assert {"proposal.created", "proposal.approved", "tool.executed"} <= actions


async def test_unrecognised_text_goes_to_the_llm(client, parse_sse):
    session = (await client.post("/api/chat/sessions", json={})).json()
    response = await client.post(
        f"/api/chat/sessions/{session['id']}/messages", json={"text": "hello", "source": "text"}
    )
    events = parse_sse(response.text)
    reply = "".join(e["text"] for e in events if e["type"] == "message.delta")
    assert "fake LLM" in reply
    assert events[-1]["type"] == "message.done"


async def test_remember_files_a_suggestion_that_needs_approval(client, parse_sse):
    session = (await client.post("/api/chat/sessions", json={})).json()
    response = await client.post(
        f"/api/chat/sessions/{session['id']}/messages",
        json={"text": "Remember that my advisor is Dr. Lee.", "source": "text"},
    )
    events = parse_sse(response.text)
    assert any(e["type"] == "tool.result" and "advisor" in e["summary"] for e in events)
    assert (await client.get("/api/memory/facts")).json() == []  # not stored yet

    [suggestion] = (await client.get("/api/memory/suggestions")).json()
    assert suggestion["source"] == f"chat:{session['id']}"
    decided = await client.post(
        f"/api/memory/suggestions/{suggestion['id']}/decision", json={"decision": "approve"}
    )
    assert decided.json()["status"] == "approved"
    [fact] = (await client.get("/api/memory/facts")).json()
    assert fact["text"] == "my advisor is Dr. Lee"


async def test_tools_endpoint_exposes_argument_schemas(client):
    tools = {t["name"]: t for t in (await client.get("/api/tools")).json()}
    assert set(tools) == {
        "create_reminder",
        "create_task",
        "list_reminders",
        "search_email",
        "send_email",
        "list_events",
        "create_event",
        "find_free_time",
    }
    assert tools["list_reminders"]["read_only"] is True
    assert "due_at" in tools["create_reminder"]["parameters"]["properties"]
    # the web Edit form reads these hints: a list field and a multi-line body
    email = tools["send_email"]["parameters"]["properties"]
    assert email["to"]["type"] == "array" and email["body"]["format"] == "multiline"


async def test_unknown_session_is_404(client):
    response = await client.post(
        "/api/chat/sessions/nope/messages", json={"text": "hi", "source": "text"}
    )
    assert response.status_code == 404


async def test_today_board(client):
    session = (await client.post("/api/chat/sessions", json={})).json()
    await client.post(
        f"/api/chat/sessions/{session['id']}/messages",
        json={"text": "remind me to stretch at 3pm", "source": "text"},
    )
    today = (await client.get("/api/today")).json()
    assert today["date"] == "2026-10-05"
    assert len(today["pending_proposals"]) == 1
