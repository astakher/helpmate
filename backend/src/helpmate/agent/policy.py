"""Policy engine: the only path by which a tool call becomes an action.

- read-only tools run immediately
- a tool the owner pre-approved (PermissionSettings.permitted, empty by default) runs
  immediately too, but only if it changes HelpMate's own data (Risk.WRITE): email and calendar
  actions always ask, so a message can't talk the assistant into sending or booking anything
- every other tool call becomes a pending Proposal; it executes only via `decide(approve|edit)`
- every step is written to the audit log, with the action's title

Invariant (tested in tests/test_policy.py): no non-read-only tool executes without an approval
or the owner's explicit pre-approval.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from helpmate.agent.tools import Tool, ToolDeps, ToolRegistry, ToolReply
from helpmate.domain.models import (
    Actor,
    AuditEntry,
    EmailSummary,
    Proposal,
    ProposalStatus,
    Risk,
    ToolCall,
    new_id,
)

Decision = Literal["approve", "reject", "edit"]


def pre_approvable(tool: Tool[Any]) -> bool:
    """Can the owner put this tool on the pre-approved list? Only if it changes HelpMate's own
    data: anything that leaves the machine (an email, a calendar event) always asks."""
    return not tool.read_only and tool.risk == Risk.WRITE


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
    emails: list[EmailSummary] = field(default_factory=list)  # shown as cards (search_email)


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
            try:
                result = await tool.execute(args, self._deps)
            except Exception as exc:  # e.g. Google not connected: the chat says so
                await self._audit(Actor.AGENT, "tool.failed", call.name, error=str(exc))
                return ToolOutcome(ok=False, summary=f"Couldn't run {call.name}: {exc}")
            await self._audit(Actor.AGENT, "tool.executed", call.name, read_only=True)
            if isinstance(result, ToolReply):
                return ToolOutcome(ok=True, summary=result.text, emails=result.emails)
            return ToolOutcome(ok=True, summary=result)

        title, summary = tool.describe(args, self._deps.tz)
        permitted = (await self._deps.repos.settings.get_permissions()).permitted
        if pre_approvable(tool) and tool.name in permitted:
            return await self._run_pre_approved(tool, args, title)
        proposal = Proposal(
            id=new_id(),
            session_id=session_id,
            tool=tool.name,
            title=title,
            summary=summary,
            args=args.model_dump(mode="json"),
            preview=tool.preview(args) if tool.preview else None,
            warnings=await self._warnings(tool, args),
            risk=tool.risk,
            created_at=self._deps.clock.now(),
        )
        await self._deps.repos.proposals.add(proposal)
        await self._audit(Actor.AGENT, "proposal.created", proposal.id, tool=tool.name, title=title)
        return ToolOutcome(ok=True, summary=f"Waiting for approval: {title}", proposal=proposal)

    async def _run_pre_approved(self, tool: Tool[Any], args: BaseModel, title: str) -> ToolOutcome:
        """The owner put this tool on the pre-approved list: run it now, and say so."""
        try:
            result = await tool.execute(args, self._deps)
        except Exception as exc:
            await self._audit(
                Actor.AGENT,
                "tool.failed",
                tool.name,
                tool=tool.name,
                title=title,
                pre_approved=True,
                error=str(exc),
            )
            return ToolOutcome(ok=False, summary=f"Couldn't do it: {exc}")
        await self._audit(
            Actor.AGENT, "tool.executed", tool.name, tool=tool.name, title=title, pre_approved=True
        )
        text = result.text if isinstance(result, ToolReply) else result
        return ToolOutcome(ok=True, summary=f"Done without asking, as you pre-approved it: {text}")

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
            await self._audit(
                Actor.USER,
                "proposal.rejected",
                proposal.id,
                tool=proposal.tool,
                title=proposal.title,
            )
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
            proposal.preview = tool.preview(parsed) if tool.preview else None
            proposal.warnings = await self._warnings(tool, parsed)

        action = "proposal.edited" if decision == "edit" else "proposal.approved"
        await self._audit(Actor.USER, action, proposal.id, tool=proposal.tool, title=proposal.title)
        try:
            result = await tool.execute(parsed, self._deps)
            proposal.result = result.text if isinstance(result, ToolReply) else result
            proposal.status = ProposalStatus.EXECUTED
            await self._audit(
                Actor.SYSTEM, "tool.executed", proposal.id, tool=proposal.tool, title=proposal.title
            )
        except Exception as exc:  # the card shows the failure; the audit log keeps it
            proposal.result = f"Failed: {exc}"
            proposal.status = ProposalStatus.FAILED
            await self._audit(
                Actor.SYSTEM,
                "tool.failed",
                proposal.id,
                tool=proposal.tool,
                title=proposal.title,
                error=str(exc),
            )
        await self._deps.repos.proposals.update(proposal)
        return proposal

    async def _warnings(self, tool: Tool[Any], args: BaseModel) -> list[str]:
        """The tool's pre-approval check (e.g. calendar overlaps). A failing check never blocks
        the card: the owner sees that it couldn't run instead."""
        if tool.check is None:
            return []
        try:
            return await tool.check(args, self._deps)
        except Exception as exc:
            return [f"Couldn't check this first: {exc}"]

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
