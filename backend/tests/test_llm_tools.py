# Stand-in for Workstream A - not part of the Part C deliverable
"""The model-facing tool layer (agent/llm_tools.py) resolves to the unchanged canonical tools."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from helpmate.agent import llm_tools
from helpmate.agent.tools import default_registry

TZ = ZoneInfo("America/Toronto")
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=TZ)  # Monday noon


def resolve(name: str, **arguments):
    return llm_tools.resolve(name, arguments, default_registry(), NOW, TZ)


def test_reminder_time_words_are_resolved_in_code():
    args = resolve("create_reminder", text="take the laundry out", when="in 10 minutes")
    assert args == {
        "text": "take the laundry out",
        "due_at": "2026-10-05T12:10:00-04:00",
        "recurrence": None,
    }


def test_weekly_repeat_from_enum_fields():
    args = resolve(
        "create_reminder", text="plan my week", when="8am", repeat="weekly", weekday="monday"
    )
    assert args["due_at"] == "2026-10-12T08:00:00-04:00"
    assert args["recurrence"] == "FREQ=WEEKLY;BYDAY=MO"


def test_repeat_words_inside_when_are_enough():
    args = resolve("create_reminder", text="plan my week", when="every Monday at 8am")
    assert args["recurrence"] == "FREQ=WEEKLY;BYDAY=MO"


def test_canonical_due_at_is_still_accepted():
    args = resolve("create_reminder", text="x", due_at="2026-10-06T09:00:00-04:00")
    assert args["due_at"] == "2026-10-06T09:00:00-04:00"


def test_unclear_time_gives_the_model_a_fix():
    with pytest.raises(llm_tools.ResolveError, match="in 10 minutes"):
        resolve("create_reminder", text="x", when="PT10M")


def test_task_horizon_is_normalised():
    assert resolve("create_task", title="read ch. 3", horizon="This Term") == {
        "title": "read ch. 3",
        "horizon": "term",
        "due_at": None,
    }
    with pytest.raises(llm_tools.ResolveError, match="horizon"):
        resolve("create_task", title="x", horizon="next decade")


def test_unknown_tool():
    with pytest.raises(llm_tools.ResolveError, match="plain text"):
        resolve("delete_everything", confirm=True)


def test_model_specs_differ_but_canonical_schemas_are_untouched():
    registry = default_registry()
    specs = {s.name: s.parameters for s in llm_tools.specs(registry)}
    reminder = specs["create_reminder"]["properties"]
    assert "when" in reminder and "due_at" not in reminder
    assert reminder["repeat"]["enum"] == ["none", "daily", "weekdays", "weekly"]
    # GET /api/tools (the web Edit form) and the policy engine still use the canonical models
    canonical = registry.get("create_reminder").args_model.model_json_schema()["properties"]
    assert set(canonical) == {"text", "due_at", "recurrence"}


def test_system_prompt_has_the_date_and_the_no_tool_rule():
    prompt = llm_tools.system_prompt(NOW, TZ)
    assert "Monday 2026-10-05 12:00" in prompt and "call NO tool" in prompt
