"""Policy engine: the only path by which a tool call becomes an action.

- read-only tools run immediately
- every other tool call becomes a pending Proposal; it executes only via `decide(approve|edit)`
- every step is written to the audit log

Invariant (tested in tests/test_policy.py): no non-read-only tool executes without an approval.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import ValidationError

from helpmate.agent.tools import ToolDeps, ToolRegistry
from helpmate.domain.models import (
    Actor,
    AuditEntry,
    Proposal,
    ProposalStatus,
    ToolCall,
    new_id,
)

Decision = Literal["approve", "reject", "edit"]


class ProposalNotFound(LookupError):
    pass


class ProposalAlreadyDecided(RuntimeError):
    pass


class InvalidToolArgs(ValueError):
    pass


@dataclass(frozen=True)
class ToolOutcome:
    ok: bool
    summary: str
    proposal: Proposal | None = None  # set when the call needs approval


class PolicyEngine:
    def __init__(self, tools: ToolRegistry, deps: ToolDeps) -> None:
        self._tools = tools
        self._deps = deps

    @property
    def tools(self) -> ToolRegistry:
        return self._tools

    async def handle_call(self, call: ToolCall, session_id: str | None = None) -> ToolOutcome:
        tool = self._tools.get(call.name)
        if tool is None:
            await self._audit(Actor.AGENT, "tool.rejected", call.name, reason="unknown tool")
            return ToolOutcome(ok=False, summary=f"Unknown tool {call.name!r}.")
        try:
            args = tool.args_model.model_validate(call.arguments)
        except ValidationError as exc:
            await self._audit(Actor.AGENT, "tool.rejected", call.name, reason="invalid args")
            return ToolOutcome(ok=False, summary=f"Invalid arguments for {call.name}: {exc}")

        if tool.read_only:
            result = await tool.execute(args, self._deps)
            await self._audit(Actor.AGENT, "tool.executed", call.name, read_only=True)
            return ToolOutcome(ok=True, summary=result)

        title, summary = tool.describe(args, self._deps.tz)
        proposal = Proposal(
            id=new_id(),
            session_id=session_id,
            tool=tool.name,
            title=title,
            summary=summary,
            args=args.model_dump(mode="json"),
            preview=tool.preview(args) if tool.preview else None,
            risk=tool.risk,
            created_at=self._deps.clock.now(),
        )
        await self._deps.repos.proposals.add(proposal)
        await self._audit(Actor.AGENT, "proposal.created", proposal.id, tool=tool.name)
        return ToolOutcome(ok=True, summary=f"Waiting for approval: {title}", proposal=proposal)

    async def decide(
        self, proposal_id: str, decision: Decision, args: dict[str, Any] | None = None
    ) -> Proposal:
        proposal = await self._deps.repos.proposals.get(proposal_id)
        if proposal is None:
            raise ProposalNotFound(proposal_id)
        if proposal.status != ProposalStatus.PENDING:
            raise ProposalAlreadyDecided(f"proposal is already {proposal.status}")

        now = self._deps.clock.now()
        proposal.decided_at = now

        if decision == "reject":
            proposal.status = ProposalStatus.REJECTED
            await self._deps.repos.proposals.update(proposal)
            await self._audit(Actor.USER, "proposal.rejected", proposal.id, tool=proposal.tool)
            return proposal

        tool = self._tools.get(proposal.tool)
        if tool is None:
            raise InvalidToolArgs(f"tool {proposal.tool!r} is no longer registered")
        if decision == "edit" and args is None:
            raise InvalidToolArgs("an edit decision needs args")
        try:
            parsed = tool.args_model.model_validate(args if decision == "edit" else proposal.args)
        except ValidationError as exc:
            raise InvalidToolArgs(str(exc)) from exc
        if decision == "edit":
            proposal.args = parsed.model_dump(mode="json")
            proposal.title, proposal.summary = tool.describe(parsed, self._deps.tz)

        action = "proposal.edited" if decision == "edit" else "proposal.approved"
        await self._audit(Actor.USER, action, proposal.id, tool=proposal.tool)
        try:
            proposal.result = await tool.execute(parsed, self._deps)
            proposal.status = ProposalStatus.EXECUTED
            await self._audit(Actor.SYSTEM, "tool.executed", proposal.id, tool=proposal.tool)
        except Exception as exc:  # the card shows the failure; the audit log keeps it
            proposal.result = f"Failed: {exc}"
            proposal.status = ProposalStatus.FAILED
            await self._audit(
                Actor.SYSTEM, "tool.failed", proposal.id, tool=proposal.tool, error=str(exc)
            )
        await self._deps.repos.proposals.update(proposal)
        return proposal

    async def _audit(self, actor: Actor, action: str, target: str | None, **detail: Any) -> None:
        await self._deps.repos.audit.add(
            AuditEntry(
                id=new_id(),
                at=self._deps.clock.now(),
                actor=actor,
                action=action,
                target=target,
                detail=detail,
            )
        )
