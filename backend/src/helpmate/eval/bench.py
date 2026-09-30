# Stand-in for Workstream A - not part of the Part C deliverable
"""Model benchmark: which local model should HelpMate use on this machine?

For each model it measures load time, GPU offload / VRAM, time to first token, generation speed,
and tool-calling quality on the seed prompts (golden_seed.jsonl) using HelpMate's real tool
definitions. Results go to docs/benchmarks/<host>[-<tag>].md (+ .json).

    cd backend
    uv run helpmate-bench                                  # llama3.2:3b and qwen3:4b
    uv run helpmate-bench --models llama3.2:3b llama3.1:8b --runs 3
    uv run helpmate-bench --models llama3.2:3b --pipeline baseline --cases holdout --tag x

Pipelines:
- improved (default): agent/llm_tools.py. Model-facing tool specs + system prompt; the owner's
  time words are resolved to due_at in code; invalid calls are sent back once (validate-and-retry).
  "Args valid" then means the resolved args pass the canonical models.
- routed: improved, plus a first classification call with no tools attached (structured output);
  then a plain reply with no tools, or a call offering only the chosen tool with only that tool's
  rules (llm_tools.tool_prompt), as the LoopAgent does.
- baseline: the Sep 29 setup. Canonical specs, the model must write ISO datetimes, no retry.

Case sets: golden_seed.jsonl (15, also used while designing the improved prompt),
golden_holdout.jsonl (16, written before any improved run and never used for tuning) and
golden_connectors.jsonl (18: email + calendar, and look-alikes that must NOT use them).
Checks: `field~` contains; `due|start|end_local` "+N HH:MM" (N days from today);
`due|start|end_next_local` "[MO ]HH:MM" (the next such local time); `asks_owner` (the call is
right to stop and ask, e.g. no email address given); anything else must be equal.

Needs Ollama running locally (OLLAMA_HOST=127.0.0.1:11434). Temperature is 0 so runs are
comparable.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import shutil
import statistics
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from datetime import time as dtime
from importlib import resources
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import httpx
from pydantic import ValidationError

from helpmate.agent import llm_tools
from helpmate.agent.tools import ToolRegistry, default_registry
from helpmate.agent.when import WEEKDAYS
from helpmate.settings import REPO_ROOT, Settings

DEFAULT_MODELS = ["llama3.2:3b", "qwen3:4b"]
CASE_FILES = {
    "seed": "golden_seed.jsonl",
    "holdout": "golden_holdout.jsonl",
    "connectors": "golden_connectors.jsonl",
}
_TIME_FIELDS = {"due": "due_at", "start": "start", "end": "end"}
Pipeline = Literal["baseline", "improved", "routed"]
PIPELINE_NOTES = {
    "baseline": "model writes ISO datetimes itself, no retry",
    "improved": "time words resolved in code, validate-and-retry once; see agent/llm_tools.py",
    "routed": "improved + a no-tools classification call first, then only the chosen tool "
    "(TTFT includes the classification)",
}


@dataclass
class Case:
    id: str
    prompt: str
    tool: str | None
    checks: dict[str, Any]


@dataclass
class CaseResult:
    id: str
    ttft_ms: float | None
    total_ms: float
    tokens_per_s: float | None
    prompt_tokens_per_s: float | None
    called: str | None
    tool_ok: bool
    args_strict_ok: bool | None  # args pass HelpMate's pydantic validation as-is
    checks_ok: bool | None  # content/time checks, with naive datetimes read as local time
    notes: list[str] = field(default_factory=list)
    retried: bool = False  # improved pipeline: the first call was invalid and was sent back once
    route: str | None = None  # routed pipeline: what the classification step chose


@dataclass
class ModelReport:
    model: str
    load_s: float
    gpu_percent: float | None
    vram_gb: float | None
    cases: list[CaseResult]
    error: str | None = None

    def summary(self) -> dict[str, Any]:
        ttfts = [c.ttft_ms for c in self.cases if c.ttft_ms is not None]
        tps = [c.tokens_per_s for c in self.cases if c.tokens_per_s]
        tool_cases = [c for c in self.cases if c.args_strict_ok is not None]
        return {
            "model": self.model,
            "load_s": round(self.load_s, 1),
            "gpu_percent": self.gpu_percent,
            "vram_gb": self.vram_gb,
            "ttft_median_ms": _round(statistics.median(ttfts)) if ttfts else None,
            "ttft_p90_ms": _round(_percentile(ttfts, 90)) if ttfts else None,
            "tokens_per_s": _round(statistics.median(tps)) if tps else None,
            "tool_choice_pct": _pct(sum(c.tool_ok for c in self.cases), len(self.cases)),
            "args_strict_pct": _pct(
                sum(bool(c.args_strict_ok) for c in tool_cases), len(tool_cases)
            ),
            "checks_pct": _pct(sum(bool(c.checks_ok) for c in tool_cases), len(tool_cases)),
            "retries": sum(c.retried for c in self.cases),
        }


def load_cases(case_set: str = "seed") -> list[Case]:
    text = resources.files("helpmate.eval").joinpath(CASE_FILES[case_set]).read_text("utf-8")
    return [Case(**json.loads(line)) for line in text.splitlines() if line.strip()]


def system_prompt(now: datetime, tz: ZoneInfo) -> str:
    """The baseline (Sep 29) prompt. The improved one is llm_tools.system_prompt."""
    local = now.astimezone(tz)
    return (
        "You are HelpMate, a concise personal assistant running on the owner's laptop. "
        f"Current local date and time: {local:%A %Y-%m-%d %H:%M} ({tz.key}, UTC{local:%z}). "
        "Use a tool when the owner asks to create a reminder or task, or asks about their "
        "reminders. Otherwise answer briefly without tools. Datetimes in tool arguments must be "
        "ISO 8601 with the UTC offset."
    )


class Bench:
    def __init__(
        self,
        client: httpx.AsyncClient,
        tools: ToolRegistry,
        tz: ZoneInfo,
        pipeline: Pipeline = "improved",
    ) -> None:
        self._client = client
        self._tools = tools
        self._tz = tz
        self.pipeline = pipeline

    async def ollama_version(self) -> str:
        response = await self._client.get("/api/version")
        response.raise_for_status()
        return response.json().get("version", "?")

    async def run_model(self, model: str, cases: list[Case], runs: int) -> ModelReport:
        try:
            load_s = await self._load(model)
            gpu_percent, vram_gb = await self._placement(model)
            results = [await self._run_case(model, case) for _ in range(runs) for case in cases]
        except (httpx.HTTPError, RuntimeError) as exc:
            return ModelReport(model, 0.0, None, None, [], error=str(exc))
        return ModelReport(model, load_s, gpu_percent, vram_gb, results)

    async def _load(self, model: str) -> float:
        started = time.perf_counter()
        response = await self._client.post(
            "/api/generate", json={"model": model, "prompt": "", "keep_alive": "10m"}
        )
        if response.status_code == 404:
            raise RuntimeError(f"model {model!r} not pulled — run: ollama pull {model}")
        response.raise_for_status()
        return time.perf_counter() - started

    async def _placement(self, model: str) -> tuple[float | None, float | None]:
        response = await self._client.get("/api/ps")
        response.raise_for_status()
        for running in response.json().get("models", []):
            if running.get("name") == model or running.get("model") == model:
                size, vram = running.get("size") or 0, running.get("size_vram") or 0
                percent = round(100 * vram / size) if size else None
                return percent, round(vram / 1e9, 2)
        return None, None

    async def _run_case(self, model: str, case: Case) -> CaseResult:
        now = datetime.now(self._tz)
        improved = self.pipeline in ("improved", "routed")
        prompt = (llm_tools.system_prompt if improved else system_prompt)(now, self._tz)
        specs = llm_tools.specs(self._tools) if improved else self._tools.specs()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": case.prompt},
        ]

        started = time.perf_counter()
        route = None
        if self.pipeline == "routed":
            route = await self._route(model, case.prompt)
            specs = [s for s in specs if s.name == route]  # "reply" -> no tools at all
            if route != "reply":  # the LoopAgent gives a routed call only that tool's rules
                messages[0]["content"] = llm_tools.tool_prompt(route, now, self._tz)
        first, calls, final = await self._chat(model, messages, specs)
        resolved: dict[str, Any] | None = None
        error: llm_tools.ResolveError | None = None
        retried = False
        if improved and calls:
            resolved, error = self._resolve(calls[0], now, case.prompt)
            if error and not isinstance(error, llm_tools.NeedsOwner):  # validate-and-retry once
                retried = True
                messages += [
                    {"role": "assistant", "content": "", "tool_calls": calls[:1]},
                    {
                        "role": "tool",
                        "tool_name": calls[0]["function"]["name"],
                        "content": f"Error: {error} Call the tool again with corrected "
                        "arguments, or reply in plain text.",
                    },
                ]
                _, calls, final = await self._chat(model, messages, specs)
                resolved, error = (
                    self._resolve(calls[0], now, case.prompt) if calls else (None, None)
                )
        total_ms = (time.perf_counter() - started) * 1000
        result = self._score(
            case, calls, now, first, started, total_ms, final, resolved, error, retried
        )
        result.route = route
        if route is not None and not result.tool_ok:
            result.notes.insert(0, f"route={route}")
        return result

    async def _route(self, model: str, text: str) -> str:
        payload: dict[str, Any] = {
            "model": model,
            "stream": False,
            "messages": [
                {"role": "system", "content": llm_tools.ROUTER_PROMPT},
                {"role": "user", "content": text},
            ],
            "format": llm_tools.ROUTE_FORMAT,
            "options": {"temperature": 0, "num_predict": 20},
            "keep_alive": "10m",
        }
        if model.startswith("qwen3"):
            payload["think"] = False
        response = await self._client.post("/api/chat", json=payload)
        response.raise_for_status()
        return llm_tools.parse_route((response.json().get("message") or {}).get("content", ""))

    async def _chat(
        self, model: str, messages: list[dict[str, Any]], specs: list[Any]
    ) -> tuple[float | None, list[dict[str, Any]], dict[str, Any]]:
        payload: dict[str, Any] = {
            "model": model,
            "stream": True,
            "messages": messages,
            "tools": [{"type": "function", "function": s.model_dump()} for s in specs],
            "options": {"temperature": 0},
            "keep_alive": "10m",
        }
        if model.startswith("qwen3"):
            payload["think"] = False

        content = ""
        chunks: list[tuple[float, int]] = []  # (arrival time, len(content) so far)
        tool_at: float | None = None
        calls: list[dict[str, Any]] = []
        final: dict[str, Any] = {}
        async with self._client.stream("POST", "/api/chat", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                chunk = json.loads(line)
                message = chunk.get("message") or {}
                if text := message.get("content"):
                    content += text
                    chunks.append((time.perf_counter(), len(content)))
                if message.get("tool_calls"):
                    tool_at = tool_at or time.perf_counter()
                    calls.extend(message["tool_calls"])
                if chunk.get("done"):
                    final = chunk
        return _first_visible(content, chunks, tool_at), calls, final

    def _resolve(
        self, call: dict[str, Any], now: datetime, said: str
    ) -> tuple[dict[str, Any] | None, llm_tools.ResolveError | None]:
        function = call.get("function") or {}
        try:
            args = llm_tools.resolve(
                function.get("name", ""), _arguments(call), self._tools, now, self._tz, said=said
            )
        except llm_tools.ResolveError as exc:
            return None, exc
        return args, None

    def _score(
        self,
        case: Case,
        calls: list[dict[str, Any]],
        now: datetime,
        first: float | None,
        started: float,
        total_ms: float,
        final: dict[str, Any],
        resolved: dict[str, Any] | None = None,
        error: llm_tools.ResolveError | None = None,
        retried: bool = False,
    ) -> CaseResult:
        called = calls[0]["function"]["name"] if calls else None
        args: dict[str, Any] = _arguments(calls[0]) if calls else {}
        result = CaseResult(
            id=case.id,
            ttft_ms=_round((first - started) * 1000) if first else None,
            total_ms=_round(total_ms),
            tokens_per_s=_rate(final.get("eval_count"), final.get("eval_duration")),
            prompt_tokens_per_s=_rate(
                final.get("prompt_eval_count"), final.get("prompt_eval_duration")
            ),
            called=called,
            tool_ok=called == case.tool,
            args_strict_ok=None,
            checks_ok=None,
            retried=retried,
        )
        if case.tool is None or not result.tool_ok:
            return result
        if case.checks.get("asks_owner"):  # right to stop and ask the owner
            result.args_strict_ok = result.checks_ok = isinstance(error, llm_tools.NeedsOwner)
            if not result.checks_ok:
                result.notes.append(f"expected to ask the owner, got {resolved or error}")
            return result
        if self.pipeline in ("improved", "routed"):
            result.args_strict_ok = resolved is not None
            if error:
                result.notes.append(f"invalid{' after retry' if retried else ''}: {error}")
            args = resolved if resolved is not None else args
        else:
            tool = self._tools.get(case.tool)
            assert tool is not None
            try:
                tool.args_model.model_validate(args)
                result.args_strict_ok = True
            except ValidationError as exc:
                result.args_strict_ok = False
                result.notes.append(f"strict: {exc.errors()[0]['msg']}")
        result.checks_ok, notes = check_args(args, case.checks, now, self._tz)
        result.notes += notes
        return result


def check_args(
    args: dict[str, Any], checks: dict[str, Any], now: datetime, tz: ZoneInfo
) -> tuple[bool, list[str]]:
    """Content checks. Naive datetimes are read as owner-local time, so a model that gets the time
    right but omits the offset still passes here (and fails only `args_strict_ok`)."""
    notes: list[str] = []
    for key, expected in checks.items():
        if key.endswith("~"):
            value = str(args.get(key[:-1], ""))
            if str(expected).lower() not in value.lower():
                notes.append(f"{key[:-1]}={value!r} lacks {expected!r}")
        elif key == "due_in_minutes":
            due = _parse_dt(args.get("due_at"), tz)
            target = now + timedelta(minutes=expected)
            if due is None or abs((due - target).total_seconds()) > 120:
                notes.append(f"due_at={args.get('due_at')!r}, expected ~{target:%H:%M}")
        elif key.endswith("_next_local"):  # "[MO ]HH:MM": the next such local time after now
            name = _TIME_FIELDS[key.removesuffix("_next_local")]
            *day, hhmm = expected.split(" ")
            hour, minute = map(int, hhmm.split(":"))
            target = _next_local(now, tz, hour, minute, day[0] if day else None)
            due = _parse_dt(args.get(name), tz)
            if due is None or due.astimezone(tz).replace(second=0, microsecond=0) != target:
                notes.append(f"{name}={args.get(name)!r}, expected {target:%a %Y-%m-%d %H:%M}")
        elif key.endswith("_local"):  # "+N HH:MM": N days from today at HH:MM
            name = _TIME_FIELDS[key.removesuffix("_local")]
            day_offset, hhmm = expected.split(" ")
            hour, minute = map(int, hhmm.split(":"))
            target_date = now.astimezone(tz).date() + timedelta(days=int(day_offset))
            due = _parse_dt(args.get(name), tz)
            local = due.astimezone(tz) if due else None
            if local is None or (local.date(), local.hour, local.minute) != (
                target_date,
                hour,
                minute,
            ):
                notes.append(f"{name}={args.get(name)!r}, expected {target_date} {hhmm}")
        elif args.get(key) != expected:
            notes.append(f"{key}={args.get(key)!r}, expected {expected!r}")
    return not notes, notes


def render_markdown(host: dict[str, str], reports: list[ModelReport]) -> str:
    lines = [
        f"# Model benchmark — {host['host']}",
        "",
        f"- Date: {host['date']}",
        f"- GPU: {host['gpu']}",
        f"- Ollama: {host['ollama']}",
        f"- Prompts: {host['cases']} {host.get('case_set', 'seed')} cases x {host['runs']} run(s), "
        "temperature 0",
        f"- Pipeline: {host.get('pipeline', 'baseline')} "
        f"({PIPELINE_NOTES[host.get('pipeline', 'baseline')]})",
        "",
        "| Model | Load s | GPU % | VRAM GB | TTFT median ms | TTFT p90 ms | tok/s | "
        "Tool choice | Args valid (strict) | Args correct | Retries |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for report in reports:
        if report.error:
            lines.append(f"| {report.model} | error: {report.error} ||||||||||")
            continue
        s = report.summary()
        lines.append(
            f"| {s['model']} | {s['load_s']} | {_fmt(s['gpu_percent'])} | {_fmt(s['vram_gb'])} | "
            f"{_fmt(s['ttft_median_ms'])} | {_fmt(s['ttft_p90_ms'])} | {_fmt(s['tokens_per_s'])} | "
            f"{s['tool_choice_pct']}% | {s['args_strict_pct']}% | {s['checks_pct']}% | "
            f"{s['retries']} |"
        )
    lines += [
        "",
        "Targets from the spec: text first word ≤ 1.5 s, tool choice ≥ 90 %, valid args ≥ 95 %, "
        "GPU 100 % (no CPU spill).",
        "",
        "## Misses",
        "",
    ]
    for report in reports:
        misses = [c for c in report.cases if not c.tool_ok or c.checks_ok is False]
        if misses:
            lines.append(f"**{report.model}**")
            lines += [
                f"- `{c.id}`: called `{c.called}`" + (f" — {'; '.join(c.notes)}" if c.notes else "")
                for c in misses
            ]
            lines.append("")
    return "\n".join(lines) + "\n"


def host_info(
    ollama: str, cases: int, runs: int, pipeline: str = "improved", case_set: str = "seed"
) -> dict[str, str]:
    gpu = "unknown (nvidia-smi not found)"
    if shutil.which("nvidia-smi"):
        query = ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"]
        try:
            gpu = subprocess.run(query, capture_output=True, text=True, timeout=10).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return {
        "host": platform.node() or "unknown-host",
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "gpu": gpu,
        "ollama": ollama,
        "cases": str(cases),
        "runs": str(runs),
        "pipeline": pipeline,
        "case_set": case_set,
    }


async def collect(
    models: list[str],
    runs: int,
    settings: Settings,
    pipeline: Pipeline = "improved",
    case_set: str = "seed",
) -> tuple[dict[str, str], list[ModelReport]]:
    cases = load_cases(case_set)
    async with httpx.AsyncClient(
        base_url=settings.ollama_url, timeout=httpx.Timeout(300.0, connect=5.0)
    ) as client:
        bench = Bench(client, default_registry(), settings.tz, pipeline)
        try:
            version = await bench.ollama_version()
        except httpx.ConnectError as exc:
            raise SystemExit(
                f"Ollama is not reachable at {settings.ollama_url}. Start it (tray icon) and retry."
            ) from exc
        reports = []
        for model in models:
            print(f"benchmarking {model} ...", flush=True)
            reports.append(await bench.run_model(model, cases, runs))
    return host_info(version, len(cases), runs, pipeline, case_set), reports


def write_report(
    out_dir: Path, info: dict[str, str], reports: list[ModelReport], tag: str | None = None
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = info["host"].lower().replace(" ", "-") + (f"-{tag}" if tag else "")
    markdown = render_markdown(info, reports)
    (out_dir / f"{stem}.md").write_text(markdown, encoding="utf-8", newline="\n")
    raw = {"host": info, "reports": [asdict(r) | {"summary": r.summary()} for r in reports]}
    (out_dir / f"{stem}.json").write_text(json.dumps(raw, indent=2), encoding="utf-8")
    print(markdown)
    return out_dir / f"{stem}.md"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    parser.add_argument("--runs", type=int, default=1, help="repeat each prompt N times")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "docs" / "benchmarks")
    parser.add_argument("--pipeline", choices=sorted(PIPELINE_NOTES), default="improved")
    parser.add_argument("--cases", choices=sorted(CASE_FILES), default="seed")
    parser.add_argument("--tag", help="suffix for the report file name, e.g. holdout-baseline")
    args = parser.parse_args()
    info, reports = asyncio.run(
        collect(args.models, args.runs, Settings(), args.pipeline, args.cases)
    )
    print(f"wrote {write_report(args.out, info, reports, args.tag)}")


def _rate(count: int | None, duration_ns: int | None) -> float | None:
    return _round(count / (duration_ns / 1e9)) if count and duration_ns else None


def _percentile(values: list[float], pct: int) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(pct / 100 * (len(ordered) - 1)))]


def _pct(numerator: int, denominator: int) -> int:
    return round(100 * numerator / denominator) if denominator else 0


def _round(value: float) -> float:
    return round(value, 1)


def _fmt(value: object) -> str:
    return "–" if value is None else str(value)


def _arguments(call: dict[str, Any]) -> dict[str, Any]:
    raw = (call.get("function") or {}).get("arguments") or {}
    if isinstance(raw, str):  # some models send the arguments as a JSON string
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return raw if isinstance(raw, dict) else {}


def _first_visible(
    content: str, chunks: list[tuple[float, int]], tool_at: float | None
) -> float | None:
    """When the first answer text or tool call arrived, skipping <think>…</think> reasoning.
    Thinking builds (qwen3:4b) stream their reasoning as content, often without the opening tag
    (the chat template adds it), so everything up to the last </think> counts as thinking."""
    end = content.rfind("</think>")
    if end >= 0:
        start = end + len("</think>")
    elif content.lstrip().startswith("<think>"):
        start = len(content)
    else:
        start = 0
    start += len(content[start:]) - len(content[start:].lstrip())
    text_at = next((t for t, length in chunks if length > start), None)
    times = [t for t in (text_at, tool_at) if t is not None]
    return min(times) if times else None


def _next_local(
    now: datetime, tz: ZoneInfo, hour: int, minute: int, day: str | None
) -> datetime | None:
    local = now.astimezone(tz)
    for offset in range(8):
        candidate = datetime.combine(local.date() + timedelta(days=offset), dtime(hour, minute), tz)
        if candidate > local and (day is None or WEEKDAYS[candidate.weekday()][:2].upper() == day):
            return candidate
    return None


def _parse_dt(value: object, tz: ZoneInfo) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=tz)


if __name__ == "__main__":
    main()
