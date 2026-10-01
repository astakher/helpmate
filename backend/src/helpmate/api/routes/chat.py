from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import StreamingResponse

from helpmate.api.deps import ContainerDep, current_user
from helpmate.api.schemas.bodies import CreateSessionIn, PostMessageIn
from helpmate.api.sse import SSE_HEADERS, sse_stream
from helpmate.container import Container
from helpmate.domain.events import ChatEvent, MessageDelta, MessageDone
from helpmate.domain.models import ChatMessage, ChatSession, Role, Source, new_id

router = APIRouter(prefix="/chat", tags=["chat"], dependencies=[Depends(current_user)])

TITLE_CHARS = 60


@router.post("/sessions", response_model=ChatSession, status_code=status.HTTP_201_CREATED)
async def create_session(body: CreateSessionIn, container: ContainerDep) -> ChatSession:
    session = ChatSession(id=new_id(), title=body.title, created_at=container.clock.now())
    await container.repos.chat.add_session(session)
    return session


@router.get("/sessions", response_model=list[ChatSession])
async def list_sessions(container: ContainerDep) -> list[ChatSession]:
    """The chat list, most recent activity first. A session with no messages yet isn't listed.
    Untitled sessions (from before titles existed) get their first message as the title."""
    listed = []
    for session in await container.repos.chat.find_sessions():
        if session.title is None:
            first = next(
                (m for m in await container.repos.chat.find_messages(session.id) if m.text), None
            )
            if first is None:
                continue
            session.title = chat_title(first.text)
            session.last_message_at = session.last_message_at or first.created_at
            await container.repos.chat.update_session(session)
        listed.append(session)
    return listed


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(session_id: str, container: ContainerDep) -> Response:
    """Deletes the chat and its messages for good. Approval cards it produced stay on the
    Approvals page and in the audit log."""
    if not await container.repos.chat.delete_session(session_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "chat session not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessage])
async def list_messages(session_id: str, container: ContainerDep) -> list[ChatMessage]:
    await _require_session(container, session_id)
    return await container.repos.chat.find_messages(session_id)


@router.post(
    "/sessions/{session_id}/messages",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "Server-sent events. Each frame is `event: <type>` + "
            "`data: <ChatEvent JSON>`; `: ping` comments are heartbeats.",
            "content": {
                "text/event-stream": {"schema": {"$ref": "#/components/schemas/ChatEvent"}}
            },
        }
    },
)
async def post_message(
    session_id: str, body: PostMessageIn, container: ContainerDep
) -> StreamingResponse:
    session = await _require_session(container, session_id)
    now = container.clock.now()
    await container.repos.chat.add_message(
        ChatMessage(
            id=new_id(),
            session_id=session_id,
            role=Role.USER,
            text=body.text,
            source=body.source,
            created_at=now,
        )
    )
    session.title = session.title or chat_title(body.text)
    session.last_message_at = now
    await container.repos.chat.update_session(session)
    events = _persist_reply(container, session_id, body.text, body.source)
    return StreamingResponse(
        sse_stream(events), media_type="text/event-stream", headers=SSE_HEADERS
    )


def chat_title(text: str) -> str:
    """The first message, on one line, cut at a word near TITLE_CHARS."""
    line = " ".join(text.split())
    if len(line) <= TITLE_CHARS:
        return line
    cut = line[:TITLE_CHARS].rsplit(" ", 1)[0] or line[:TITLE_CHARS]
    return cut.rstrip(" ,.;:") + "…"


async def _persist_reply(
    container: Container, session_id: str, text: str, source: Source
) -> AsyncIterator[ChatEvent]:
    """Pass the agent's events through, saving the assistant's reply when it finishes."""
    parts: list[str] = []
    async for event in container.agent.run(session_id, text, source):
        if isinstance(event, MessageDelta):
            parts.append(event.text)
        elif isinstance(event, MessageDone) and await container.repos.chat.get_session(session_id):
            # (not if the chat was deleted while this reply was streaming)
            await container.repos.chat.add_message(
                ChatMessage(
                    id=event.message_id,
                    session_id=session_id,
                    role=Role.ASSISTANT,
                    text="".join(parts),
                    created_at=container.clock.now(),
                )
            )
        yield event


async def _require_session(container: Container, session_id: str) -> ChatSession:
    session = await container.repos.chat.get_session(session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "chat session not found")
    return session
