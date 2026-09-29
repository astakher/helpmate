"""Chat stream events — what the agent yields and the web app renders.

Sent over SSE as `event: <type>` / `data: <json>`. Exported into contracts/openapi.yaml as the
`ChatEvent` component so the frontend gets a typed union.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from helpmate.domain.models import Proposal


class MessageDelta(BaseModel):
    type: Literal["message.delta"] = "message.delta"
    text: str


class ToolStarted(BaseModel):
    type: Literal["tool.started"] = "tool.started"
    call_id: str
    tool: str
    args: dict[str, Any]


class ToolResult(BaseModel):
    type: Literal["tool.result"] = "tool.result"
    call_id: str
    ok: bool
    summary: str


class ProposalCreated(BaseModel):
    type: Literal["proposal.created"] = "proposal.created"
    proposal: Proposal


class MessageDone(BaseModel):
    type: Literal["message.done"] = "message.done"
    message_id: str
    ttft_ms: int | None = None  # time to first token of the reply
    tokens: int | None = None


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    code: str
    message: str


ChatEvent = Annotated[
    MessageDelta | ToolStarted | ToolResult | ProposalCreated | MessageDone | ErrorEvent,
    Field(discriminator="type"),
]
