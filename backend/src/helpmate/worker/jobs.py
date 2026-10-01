# Stand-in for Workstream B - not part of the Part C deliverable
"""The job queue behind the scheduler: what to run, when, and what happened last time.

A job is claimed with a lease (`locked_until`) before it runs, so two workers never run it at
once, and a worker that dies mid-job only delays it until the lease runs out (at-least-once).
Finished jobs are deleted; a failing one is retried with backoff and, after MAX_ATTEMPTS, kept as
"failed" for inspection. The in-memory store is for HELPMATE_SCHEDULER=dev and tests; the
Postgres one (adapters/postgres_jobs.py, SELECT ... FOR UPDATE SKIP LOCKED) survives restarts.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any, Protocol

LEASE = timedelta(seconds=60)  # how long a claimed job is hidden from other workers
BACKOFF = (
    timedelta(seconds=30),
    timedelta(minutes=2),
    timedelta(minutes=10),
    timedelta(minutes=30),
)
MAX_ATTEMPTS = len(BACKOFF) + 1  # the first try plus one per backoff step


@dataclass(frozen=True)
class Job:
    id: str  # deterministic for idempotent enqueueing, e.g. "reminder:<id>:<due_at>"
    kind: str
    run_at: datetime
    payload: dict[str, Any] = field(default_factory=dict)
    attempts: int = 0  # incremented by claim()
    last_error: str | None = None


class JobStore(Protocol):
    name: str
    is_fake: bool

    async def put(self, job: Job) -> bool:
        """Queue `job` unless one with its id already exists (queued, leased or failed)."""
        ...

    async def claim(self, now: datetime, limit: int = 20) -> list[Job]:
        """Due, unleased jobs, oldest first, leased until now + LEASE (attempts + 1)."""
        ...

    async def complete(self, job_id: str) -> None: ...

    async def retry(self, job_id: str, run_at: datetime, error: str) -> None:
        """Release the lease and run again at `run_at`."""
        ...

    async def fail(self, job_id: str, error: str) -> None:
        """Give up: the job stays, marked failed, and is never claimed again."""
        ...

    async def next_run_at(self) -> datetime | None:
        """When the earliest queued job is due (leased ones included), for the worker's sleep."""
        ...

    async def failed(self) -> list[Job]: ...


class InMemoryJobStore:
    name = "memory"
    is_fake = True

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._locked_until: dict[str, datetime] = {}
        self._failed: set[str] = set()

    async def put(self, job: Job) -> bool:
        if job.id in self._jobs:
            return False
        self._jobs[job.id] = job
        return True

    async def claim(self, now: datetime, limit: int = 20) -> list[Job]:
        due = sorted(
            (
                j
                for j in self._jobs.values()
                if j.id not in self._failed
                and j.run_at <= now
                and self._locked_until.get(j.id, now) <= now
            ),
            key=lambda j: j.run_at,
        )[:limit]
        claimed = []
        for job in due:
            job = replace(job, attempts=job.attempts + 1)
            self._jobs[job.id] = job
            self._locked_until[job.id] = now + LEASE
            claimed.append(job)
        return claimed

    async def complete(self, job_id: str) -> None:
        self._jobs.pop(job_id, None)
        self._locked_until.pop(job_id, None)

    async def retry(self, job_id: str, run_at: datetime, error: str) -> None:
        if job_id in self._jobs:
            self._jobs[job_id] = replace(self._jobs[job_id], run_at=run_at, last_error=error)
            self._locked_until.pop(job_id, None)

    async def fail(self, job_id: str, error: str) -> None:
        if job_id in self._jobs:
            self._jobs[job_id] = replace(self._jobs[job_id], last_error=error)
            self._locked_until.pop(job_id, None)
            self._failed.add(job_id)

    async def next_run_at(self) -> datetime | None:
        queued = [j.run_at for j in self._jobs.values() if j.id not in self._failed]
        return min(queued, default=None)

    async def failed(self) -> list[Job]:
        return [self._jobs[i] for i in self._failed if i in self._jobs]
