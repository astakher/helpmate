"""The model benchmark, run against a fake Ollama so it can be tested without a GPU."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from helpmate.agent.tools import default_registry
from helpmate.eval.bench import (
    Bench,
    Case,
    _first_visible,
    check_args,
    load_cases,
    render_markdown,
)

TZ = ZoneInfo("America/Toronto")


def fake_ollama(reply_for, seen: list | None = None, route_for=None):
    """reply_for(messages) -> a final /api/chat message dict. `seen` collects request bodies.
    route_for(text) -> the routed pipeline's classification (a non-streaming `format` request)."""

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
        if seen is not None:
            seen.append(body)
        if body.get("format"):
            action = route_for(body["messages"][-1]["content"])
            content = json.dumps({"action": action})
            return httpx.Response(200, json={"message": {"role": "assistant", "content": content}})
        message = reply_for(body["messages"])
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
    """Baseline pipeline: the model writes due_at itself and is scored as sent."""
    in_ten = (datetime.now(TZ) + timedelta(minutes=10)).replace(tzinfo=None).isoformat()

    def reply(messages: list) -> dict:
        prompt = messages[-1]["content"]
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
        bench = Bench(client, default_registry(), TZ, pipeline="baseline")
        report = await bench.run_model("fake:3b", cases, runs=1)

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


async def test_improved_pipeline_resolves_time_words_and_retries_once():
    seen: list = []

    def reply(messages: list) -> dict:
        prompt, retry = messages[1]["content"], len(messages) > 2
        if "laundry" in prompt:
            return _call("create_reminder", text="take the laundry out", when="in 10 minutes")
        if "oven" in prompt:  # first answer can't be resolved; the corrected one can
            when = "in 30 minutes" if retry else "PT30M"
            return _call("create_reminder", text="check the oven", when=when)
        return {"role": "assistant", "content": "Hi! How can I help?"}

    laundry = "remind me in 10 minutes to take the laundry out"
    oven = "in half an hour remind me to check the oven"
    cases = [
        Case("in", laundry, "create_reminder", {"text~": "laundry", "due_in_minutes": 10}),
        Case("retry", oven, "create_reminder", {"text~": "oven", "due_in_minutes": 30}),
        Case("hi", "Hi!", None, {}),
    ]
    async with fake_ollama(reply, seen) as client:
        report = await Bench(client, default_registry(), TZ).run_model("fake:3b", cases, runs=1)

    by_id = {c.id: c for c in report.cases}
    assert by_id["in"].args_strict_ok and by_id["in"].checks_ok and not by_id["in"].retried
    assert by_id["retry"].retried and by_id["retry"].args_strict_ok and by_id["retry"].checks_ok
    assert by_id["hi"].tool_ok and report.summary()["retries"] == 1

    tools = {t["function"]["name"]: t["function"] for t in seen[-1]["tools"]}
    assert "when" in tools["create_reminder"]["parameters"]["properties"]
    retry_request = next(b for b in seen if len(b["messages"]) > 2)
    assert retry_request["messages"][-1]["role"] == "tool"
    assert "in 10 minutes" in retry_request["messages"][-1]["content"]  # tells it what works


async def test_routed_pipeline_offers_no_tools_for_small_talk_and_one_tool_otherwise():
    seen: list = []

    def reply(messages: list) -> dict:
        if "laundry" in messages[1]["content"]:
            return _call("create_reminder", text="laundry", when="in 10 minutes")
        return {"role": "assistant", "content": "Ottawa."}

    def route(text: str) -> str:
        return "create_reminder" if "laundry" in text else "reply"

    laundry = "remind me in 10 minutes to take the laundry out"
    cases = [
        Case("in", laundry, "create_reminder", {"text~": "laundry", "due_in_minutes": 10}),
        Case("fact", "What's the capital of Canada?", None, {}),
    ]
    async with fake_ollama(reply, seen, route) as client:
        bench = Bench(client, default_registry(), TZ, pipeline="routed")
        report = await bench.run_model("fake:3b", cases, runs=1)

    by_id = {c.id: c for c in report.cases}
    assert by_id["in"].route == "create_reminder" and by_id["in"].checks_ok
    assert by_id["fact"].route == "reply" and by_id["fact"].tool_ok
    chats = [b for b in seen if "tools" in b]
    offered = [[t["function"]["name"] for t in b["tools"]] for b in chats]
    assert offered == [["create_reminder"], []]  # one tool for the reminder, none for the fact


def test_ttft_skips_thinking_text():
    content = "Let me think about this...</think>\n\nHello!"
    assert _first_visible(content, [(1.0, 10), (2.0, 34), (3.0, len(content))], None) == 3.0
    assert _first_visible("Hello", [(1.5, 5)], None) == 1.5
    assert _first_visible("<think>still thinking", [(1.0, 21)], 4.0) == 4.0  # then a tool call


def test_next_local_check_does_not_depend_on_when_the_bench_runs():
    evening = datetime(2026, 9, 29, 20, 33, tzinfo=TZ)  # 5 pm has passed
    check = {"due_next_local": "17:00"}
    assert check_args({"due_at": "2026-09-30T17:00:00-04:00"}, check, evening, TZ)[0]
    assert not check_args({"due_at": "2026-09-29T17:00:00-04:00"}, check, evening, TZ)[0]
    monday = {"due_next_local": "MO 08:00"}
    assert check_args({"due_at": "2026-10-05T08:00:00-04:00"}, monday, evening, TZ)[0]


def test_seed_cases_reference_real_tools():
    tools = default_registry()
    seed, holdout = load_cases("seed"), load_cases("holdout")
    assert len(seed) >= 15 and len(holdout) >= 16
    assert all(c.tool is None or c.tool in tools for c in seed + holdout)
    assert len({c.id for c in seed + holdout}) == len(seed) + len(holdout)
