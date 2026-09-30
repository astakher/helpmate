"""Part C (web app, voice, notifications) stays separable from Workstreams A and B.

Part C is copied into the group's shared repo and must plug in there unchanged, so its backend
files may import only the shared contract. See docs/part-c.md.

- Part C source files: ALLOWLIST. Only helpmate.domain, helpmate.api.deps, helpmate.api.schemas,
  helpmate.settings and other Part C modules. Third-party packages are not restricted.
- Part C test files: DENYLIST. Nothing from A or B; fakes are fine in tests.
- The speech service is its own package and never imports the backend at all.

Files that don't exist yet (Phase 6: webpush_notifier.py, quiet_hours.py) are skipped until they
are written, then checked like the rest.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
SRC = BACKEND / "src"
REPO_ROOT = BACKEND.parent

PART_C_MODULES = (
    "helpmate.adapters.speech_http",
    "helpmate.adapters.webpush_notifier",
    "helpmate.adapters.quiet_hours",
    "helpmate.api.routes.voice",
    "helpmate.api.routes.push",
    "helpmate.api.routes.settings",
)
PART_C_TESTS = (
    "tests/test_voice_and_push.py",
    "tests/test_speech_http.py",
    "tests/test_webpush.py",
    "tests/test_quiet_hours.py",
    "tests/contracts/test_notifier.py",
    "tests/test_part_c_boundary.py",
)
# Written already; the scan must never silently cover fewer than these.
EXISTING_NOW = set(PART_C_MODULES)

ALLOWED = (
    "helpmate.domain",
    "helpmate.api.deps",
    "helpmate.api.schemas",
    "helpmate.settings",
    *PART_C_MODULES,
)
FORBIDDEN_IN_TESTS = (
    "helpmate.agent",
    "helpmate.memory",
    "helpmate.eval",
    "helpmate.worker",
    "helpmate.adapters.ollama_",
    "helpmate.adapters.postgres_",
    "helpmate.adapters.gmail",
    "helpmate.adapters.gcal",
    "helpmate.adapters.s3_",
)


def _module_file(module: str) -> Path:
    return SRC.joinpath(*module.split(".")).with_suffix(".py")


def _package_of(path: Path) -> str:
    return ".".join(path.relative_to(SRC).with_suffix("").parts[:-1])


def imported_modules(source: str, package: str = "") -> list[tuple[int, list[str]]]:
    """Every import in `source` (including ones inside functions and TYPE_CHECKING blocks), as
    (line, candidate module names). `from a import b` yields both "a.b" and "a", because b may be
    a submodule or just a name; the import is allowed if either candidate is."""
    found: list[tuple[int, list[str]]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [(node.lineno, [alias.name]) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:  # relative import: resolve against the file's package
                parts = package.split(".")[: len(package.split(".")) - node.level + 1]
                base = ".".join(p for p in [*parts, base] if p)
            found += [(node.lineno, [f"{base}.{alias.name}", base]) for alias in node.names]
        elif (
            isinstance(node, ast.Call)
            and getattr(node.func, "attr", getattr(node.func, "id", None))
            in ("import_module", "__import__")
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            found.append((node.lineno, [node.args[0].value]))
    return found


def _within(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(prefix + ".")


def src_violations(source: str, package: str = "") -> list[str]:
    bad = []
    for line, candidates in imported_modules(source, package):
        internal = [m for m in candidates if _within(m, "helpmate")]
        if internal and not any(_within(m, ok) for m in internal for ok in ALLOWED):
            bad.append(f"line {line}: {candidates[0]}")
    return bad


def _forbidden_in_test(source: str) -> list[str]:
    bad = []
    for line, candidates in imported_modules(source):
        for module in candidates:
            if any(module.startswith(prefix) for prefix in FORBIDDEN_IN_TESTS):
                bad.append(f"line {line}: {module}")
                break
    return bad


@pytest.mark.parametrize("module", PART_C_MODULES)
def test_part_c_source_imports_only_the_shared_contract(module):
    path = _module_file(module)
    if not path.exists():
        assert module not in EXISTING_NOW, f"{path} was deleted or moved; update this test"
        pytest.skip(f"{module} not written yet")
    violations = src_violations(path.read_text(encoding="utf-8"), _package_of(path))
    assert not violations, (
        f"{module} imports outside the shared contract (see docs/part-c.md, rule 2): "
        + "; ".join(violations)
    )


@pytest.mark.parametrize("test_file", PART_C_TESTS)
def test_part_c_tests_import_nothing_from_a_or_b(test_file):
    path = BACKEND / test_file
    assert path.exists(), f"{test_file} is listed as a Part C test but doesn't exist"
    violations = _forbidden_in_test(path.read_text(encoding="utf-8"))
    assert not violations, f"{test_file} imports Workstream A/B code: " + "; ".join(violations)


def test_speech_service_never_imports_the_backend():
    speech = REPO_ROOT / "services" / "speech"
    files = sorted(f for d in ("src", "tests") for f in (speech / d).rglob("*.py"))
    assert files, "no speech service files found"
    for path in files:
        for line, candidates in imported_modules(path.read_text(encoding="utf-8")):
            assert not any(_within(m, "helpmate") for m in candidates), (
                f"{path.relative_to(REPO_ROOT)} line {line} imports the backend: {candidates}"
            )


@pytest.mark.parametrize(
    ("source", "ok"),
    [
        ("from helpmate.domain.models import Transcript", True),
        ("from helpmate.api.deps import ContainerDep", True),
        ("from helpmate.api import deps", True),
        ("from helpmate.api.schemas.bodies import SpeakIn", True),
        ("from helpmate import settings", True),
        ("from helpmate.adapters.speech_http import HttpSTT", True),
        ("import httpx\nfrom fastapi import APIRouter", True),
        ("from helpmate.agent.policy import PolicyEngine", False),
        ("from helpmate.adapters.fakes.log_notifier import LogNotifier", False),
        ("from helpmate.adapters.ollama_llm import OllamaLLM", False),
        ("from helpmate.container import Container", False),
        ("from helpmate.api import api_router", False),
        ("def f():\n    from helpmate.worker import queue", False),
        ("import importlib\nimportlib.import_module('helpmate.memory')", False),
        ("from .fakes import memory_repos", False),
        ("from .speech_http import HttpSTT", True),
    ],
)
def test_the_checker_itself(source, ok):
    # relative imports are resolved as if the snippet lived in helpmate/adapters/<file>.py
    assert (src_violations(source, "helpmate.adapters") == []) is ok


def test_the_test_denylist_allows_fakes_but_not_a_or_b():
    assert _forbidden_in_test("from helpmate.adapters.fakes.log_notifier import LogNotifier") == []
    assert _forbidden_in_test("from helpmate.adapters import ollama_llm")
    assert _forbidden_in_test("from helpmate.agent.policy import PolicyEngine")
