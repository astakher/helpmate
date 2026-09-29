from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from helpmate.api.deps import ContainerDep, current_user
from helpmate.api.schemas.bodies import CreateSessionIn, PostMessageIn
from helpmate.api.sse import SSE_HEADERS, sse_stream
from helpmate.container import Container
from helpmate.domain.events import ChatEvent, MessageDelta, MessageDone
from helpmate.domain.models import ChatMessage, ChatSession, Role, Source, new_id

router = APIRouter(prefix="/chat", tags=["chat"], dependencies=[Depends(current_user)])


@router.post("/sessions", response_model=ChatSession, status_code=status.HTTP_201_CREATED)
async def create_session(body: CreateSessionIn, container: ContainerDep) -> ChatSession:
    session = ChatSession(id=new_id(), title=body.title, created_at=container.clock.now())
    await container.repos.chat.add_session(session)
    return session


@router.get("/sessions", response_model=list[ChatSession])
async def list_sessions(container: ContainerDep) -> list[ChatSession]:
    return await container.repos.chat.find_sessions()


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
    await _require_session(container, session_id)
    await container.repos.chat.add_message(
        ChatMessage(
            id=new_id(),
            session_id=session_id,
            role=Role.USER,
            text=body.text,
            source=body.source,
            created_at=container.clock.now(),
        )
    )
    events = _persist_reply(container, session_id, body.text, body.source)
    return StreamingResponse(
        sse_stream(events), media_type="text/event-stream", headers=SSE_HEADERS
    )


async def _persist_reply(
    container: Container, session_id: str, text: str, source: Source
) -> AsyncIterator[ChatEvent]:
    """Pass the agent's events through, saving the assistant's reply when it finishes."""
    parts: list[str] = []
    async for event in container.agent.run(session_id, text, source):
        if isinstance(event, MessageDelta):
            parts.append(event.text)
        elif isinstance(event, MessageDone):
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


async def _require_session(container: Container, session_id: str) -> None:
    if await container.repos.chat.get_session(session_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "chat session not found")
