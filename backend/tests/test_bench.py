"""The model benchmark, run against a fake Ollama so it can be tested without a GPU."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from helpmate.agent.tools import default_registry
from helpmate.eval.bench import Bench, Case, check_args, load_cases, render_markdown

TZ = ZoneInfo("America/Toronto")


def fake_ollama(reply_for):
    """reply_for(prompt) -> a final /api/chat message dict."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/generate":
            return httpx.Response(200, json={"done": True})
        if request.url.path == "/api/ps":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {"name": "fake:3b", "size": 3_000_000_000, "size_vram": 3_000_000_000}
                    ]
                },
            )
        body = json.loads(request.content)
        message = reply_for(body["messages"][-1]["content"])
        lines = [
            {"message": {"role": "assistant", "content": ""}, "done": False},
            {
                "message": message,
                "done": True,
                "eval_count": 20,
                "eval_duration": 500_000_000,
                "prompt_eval_count": 300,
                "prompt_eval_duration": 250_000_000,
            },
        ]
        return httpx.Response(200, content="\n".join(json.dumps(x) for x in lines).encode())

    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://ollama")


def _call(name: str, **arguments) -> dict:
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"function": {"name": name, "arguments": arguments}}],
    }


async def test_scores_tool_choice_strict_args_and_content():
    in_ten = (datetime.now(TZ) + timedelta(minutes=10)).replace(tzinfo=None).isoformat()

    def reply(prompt: str) -> dict:
        if "laundry" in prompt:  # right tool, right time, but no UTC offset -> strict fail only
            return _call("create_reminder", text="take the laundry out", due_at=in_ten)
        if "groceries" in prompt:  # right tool and args
            return _call("create_task", title="buy groceries", horizon="week")
        if "capital" in prompt:  # wrongly calls a tool for a plain question
            return _call("list_reminders")
        return {"role": "assistant", "content": "Ottawa."}

    cases = [
        Case(
            "rem-in",
            "remind me in 10 minutes to take the laundry out",
            "create_reminder",
            {"text~": "laundry", "due_in_minutes": 10},
        ),
        Case("task", "add task buy groceries", "create_task", {"title~": "groceries"}),
        Case("fact", "What's the capital of Canada?", None, {}),
    ]
    async with fake_ollama(reply) as client:
        report = await Bench(client, default_registry(), TZ).run_model("fake:3b", cases, runs=1)

    by_id = {c.id: c for c in report.cases}
    assert (
        by_id["rem-in"].tool_ok and by_id["rem-in"].checks_ok and not by_id["rem-in"].args_strict_ok
    )
    assert by_id["task"].tool_ok and by_id["task"].args_strict_ok and by_id["task"].checks_ok
    assert not by_id["fact"].tool_ok and by_id["fact"].called == "list_reminders"

    summary = report.summary()
    assert summary["gpu_percent"] == 100 and summary["vram_gb"] == 3.0
    assert summary["tool_choice_pct"] == 67
    assert summary["args_strict_pct"] == 50 and summary["checks_pct"] == 100
    assert summary["tokens_per_s"] == 40.0

    markdown = render_markdown(
        {"host": "test", "date": "d", "gpu": "g", "ollama": "v", "cases": "3", "runs": "1"},
        [report],
    )
    assert "| fake:3b |" in markdown and "`fact`: called `list_reminders`" in markdown


async def test_missing_model_is_reported_not_raised():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model not found"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://o"
    ) as client:
        report = await Bench(client, default_registry(), TZ).run_model("nope:1b", [], runs=1)
    assert report.error and "ollama pull nope:1b" in report.error


def test_time_checks_use_local_wall_clock():
    now = datetime(2026, 10, 5, 12, 0, tzinfo=TZ)
    ok, _ = check_args({"due_at": "2026-10-06T09:00:00-04:00"}, {"due_local": "+1 09:00"}, now, TZ)
    wrong_offset, notes = check_args(
        {"due_at": "2026-10-06T09:00:00Z"}, {"due_local": "+1 09:00"}, now, TZ
    )
    assert ok and not wrong_offset and "expected 2026-10-06 09:00" in notes[0]


def test_seed_cases_reference_real_tools():
    tools = default_registry()
    cases = load_cases()
    assert len(cases) >= 15
    assert all(c.tool is None or c.tool in tools for c in cases)
