"""Policy engine invariants: no write executes without the owner's approval."""

from __future__ import annotations

import pytest

from helpmate.agent.policy import InvalidToolArgs, ProposalAlreadyDecided
from helpmate.domain.models import ProposalStatus, ToolCall, new_id

# Every non-read-only tool needs a sample here. Adding a write tool without one fails
# test_every_write_tool_has_a_sample, so the invariant test below always covers every write tool.
SAMPLE_ARGS = {
    "create_reminder": {"text": "call mom", "due_at": "2026-10-05T17:00:00-04:00"},
    "create_task": {"title": "read chapter 3", "horizon": "term"},
    "send_email": {"to": ["jo@example.com"], "subject": "Hi", "body": "See you at 5."},
    "create_event": {
        "title": "lunch with Sam",
        "start": "2026-10-06T12:30:00-04:00",
        "end": "2026-10-06T13:30:00-04:00",
    },
}


def _call(name: str, **args: object) -> ToolCall:
    return ToolCall(id=new_id(), name=name, arguments=args)


async def _data_snapshot(container) -> tuple[int, int, int, int]:
    return (
        len(await container.repos.reminders.find()),
        len(await container.repos.tasks.find()),
        len(container.mail.sent),
        len(container.calendar.events),
    )


def test_every_write_tool_has_a_sample(container):
    writes = {t.name for t in container.tools.all() if not t.read_only}
    assert writes <= SAMPLE_ARGS.keys(), f"add SAMPLE_ARGS for {writes - SAMPLE_ARGS.keys()}"


async def test_no_write_tool_executes_without_approval(container):
    before = await _data_snapshot(container)
    for name, args in SAMPLE_ARGS.items():
        outcome = await container.policy.handle_call(_call(name, **args))
        assert outcome.proposal is not None, name
        assert outcome.proposal.status == ProposalStatus.PENDING
    assert await _data_snapshot(container) == before


async def test_read_only_tool_runs_immediately(container):
    outcome = await container.policy.handle_call(_call("list_reminders"))
    assert outcome.proposal is None
    assert outcome.ok
    assert "no upcoming reminders" in outcome.summary


async def test_reject_executes_nothing_and_cannot_be_redecided(container):
    outcome = await container.policy.handle_call(_call("create_task", **SAMPLE_ARGS["create_task"]))
    proposal = await container.policy.decide(outcome.proposal.id, "reject")
    assert proposal.status == ProposalStatus.REJECTED
    assert await container.repos.tasks.find() == []
    with pytest.raises(ProposalAlreadyDecided):
        await container.policy.decide(outcome.proposal.id, "approve")


async def test_edit_changes_args_before_executing(container):
    outcome = await container.policy.handle_call(_call("create_task", **SAMPLE_ARGS["create_task"]))
    proposal = await container.policy.decide(
        outcome.proposal.id, "edit", {"title": "read chapter 4", "horizon": "week"}
    )
    assert proposal.status == ProposalStatus.EXECUTED
    assert proposal.title == "Task: read chapter 4"
    assert [t.title for t in await container.repos.tasks.find()] == ["read chapter 4"]


async def test_edit_with_invalid_args_is_refused(container):
    outcome = await container.policy.handle_call(_call("create_task", **SAMPLE_ARGS["create_task"]))
    with pytest.raises(InvalidToolArgs):
        await container.policy.decide(outcome.proposal.id, "edit", {"title": ""})
    assert (await container.repos.proposals.get(outcome.proposal.id)).status == "pending"


async def test_invalid_or_unknown_calls_never_become_proposals(container):
    bad = await container.policy.handle_call(_call("create_reminder", text="x"))  # no due_at
    unknown = await container.policy.handle_call(_call("delete_everything"))
    assert not bad.ok and bad.proposal is None
    assert not unknown.ok and unknown.proposal is None
    assert await container.repos.proposals.find() == []
    actions = [a.action for a in await container.repos.audit.find()]
    assert actions.count("tool.rejected") == 2


async def test_api_decision_errors(client, container):
    outcome = await container.policy.handle_call(_call("create_task", **SAMPLE_ARGS["create_task"]))
    url = f"/api/proposals/{outcome.proposal.id}/decision"
    assert (await client.post(url, json={"decision": "edit"})).status_code == 422
    assert (await client.post(url, json={"decision": "approve"})).status_code == 200
    assert (await client.post(url, json={"decision": "approve"})).status_code == 409
    missing = await client.post("/api/proposals/nope/decision", json={"decision": "approve"})
    assert missing.status_code == 404
