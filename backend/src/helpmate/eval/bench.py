"""Model benchmark: which local model should HelpMate use on this machine?

For each model it measures load time, GPU offload / VRAM, time to first token, generation speed,
and tool-calling quality on the seed prompts (golden_seed.jsonl) using HelpMate's real tool
definitions. Results go to docs/benchmarks/<host>.md (+ .json).

    cd backend
    uv run helpmate-bench                                  # llama3.2:3b and qwen3:4b
    uv run helpmate-bench --models llama3.2:3b llama3.1:8b --runs 3

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
from importlib import resources
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from pydantic import ValidationError

from helpmate.agent.tools import ToolRegistry, default_registry
from helpmate.settings import REPO_ROOT, Settings

DEFAULT_MODELS = ["llama3.2:3b", "qwen3:4b"]


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
        }


def load_cases() -> list[Case]:
    text = resources.files("helpmate.eval").joinpath("golden_seed.jsonl").read_text("utf-8")
    return [Case(**json.loads(line)) for line in text.splitlines() if line.strip()]


def system_prompt(now: datetime, tz: ZoneInfo) -> str:
    local = now.astimezone(tz)
    return (
        "You are HelpMate, a concise personal assistant running on the owner's laptop. "
        f"Current local date and time: {local:%A %Y-%m-%d %H:%M} ({tz.key}, UTC{local:%z}). "
        "Use a tool when the owner asks to create a reminder or task, or asks about their "
        "reminders. Otherwise answer briefly without tools. Datetimes in tool arguments must be "
        "ISO 8601 with the UTC offset."
    )


class Bench:
    def __init__(self, client: httpx.AsyncClient, tools: ToolRegistry, tz: ZoneInfo) -> None:
        self._client = client
        self._tools = tools
        self._tz = tz

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
        payload: dict[str, Any] = {
            "model": model,
            "stream": True,
            "messages": [
                {"role": "system", "content": system_prompt(now, self._tz)},
                {"role": "user", "content": case.prompt},
            ],
            "tools": [
                {"type": "function", "function": s.model_dump()} for s in self._tools.specs()
            ],
            "options": {"temperature": 0},
            "keep_alive": "10m",
        }
        if model.startswith("qwen3"):
            payload["think"] = False

        started = time.perf_counter()
        first: float | None = None
        calls: list[dict[str, Any]] = []
        final: dict[str, Any] = {}
        async with self._client.stream("POST", "/api/chat", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                chunk = json.loads(line)
                message = chunk.get("message") or {}
                if first is None and (message.get("content") or message.get("tool_calls")):
                    first = time.perf_counter()
                calls.extend(message.get("tool_calls") or [])
                if chunk.get("done"):
                    final = chunk
        total_ms = (time.perf_counter() - started) * 1000
        return self._score(case, calls, now, first, started, total_ms, final)

    def _score(
        self,
        case: Case,
        calls: list[dict[str, Any]],
        now: datetime,
        first: float | None,
        started: float,
        total_ms: float,
        final: dict[str, Any],
    ) -> CaseResult:
        called = calls[0]["function"]["name"] if calls else None
        args: dict[str, Any] = (calls[0]["function"].get("arguments") or {}) if calls else {}
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
        )
        if case.tool is None or not result.tool_ok:
            return result
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
        elif key == "due_local":
            day_offset, hhmm = expected.split(" ")
            hour, minute = map(int, hhmm.split(":"))
            target_date = now.astimezone(tz).date() + timedelta(days=int(day_offset))
            due = _parse_dt(args.get("due_at"), tz)
            local = due.astimezone(tz) if due else None
            if local is None or (local.date(), local.hour, local.minute) != (
                target_date,
                hour,
                minute,
            ):
                notes.append(f"due_at={args.get('due_at')!r}, expected {target_date} {hhmm}")
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
        f"- Prompts: {host['cases']} seed cases x {host['runs']} run(s), temperature 0",
        "",
        "| Model | Load s | GPU % | VRAM GB | TTFT median ms | TTFT p90 ms | tok/s | "
        "Tool choice | Args valid (strict) | Args correct |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for report in reports:
        if report.error:
            lines.append(f"| {report.model} | error: {report.error} |||||||||")
            continue
        s = report.summary()
        lines.append(
            f"| {s['model']} | {s['load_s']} | {_fmt(s['gpu_percent'])} | {_fmt(s['vram_gb'])} | "
            f"{_fmt(s['ttft_median_ms'])} | {_fmt(s['ttft_p90_ms'])} | {_fmt(s['tokens_per_s'])} | "
            f"{s['tool_choice_pct']}% | {s['args_strict_pct']}% | {s['checks_pct']}% |"
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


def host_info(ollama: str, cases: int, runs: int) -> dict[str, str]:
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
    }


async def collect(
    models: list[str], runs: int, settings: Settings
) -> tuple[dict[str, str], list[ModelReport]]:
    cases = load_cases()
    async with httpx.AsyncClient(
        base_url=settings.ollama_url, timeout=httpx.Timeout(300.0, connect=5.0)
    ) as client:
        bench = Bench(client, default_registry(), settings.tz)
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
    return host_info(version, len(cases), runs), reports


def write_report(out_dir: Path, info: dict[str, str], reports: list[ModelReport]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = info["host"].lower().replace(" ", "-")
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
    args = parser.parse_args()
    info, reports = asyncio.run(collect(args.models, args.runs, Settings()))
    print(f"wrote {write_report(args.out, info, reports)}")


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
