# Stand-in for Workstream B - not part of the Part C deliverable
"""The durable job queue (HELPMATE_SCHEDULER=pg): the `jobs` table from migration 0002.

claim() takes due rows with SELECT ... FOR UPDATE SKIP LOCKED inside a single UPDATE, so any
number of workers can poll the same table without ever running a job twice at the same time.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from helpmate.adapters.postgres_repos import Database
from helpmate.worker.jobs import LEASE, Job

_COLUMNS = "id, kind, run_at, payload, attempts, last_error"


def _job(row: Any) -> Job:
    return Job(
        id=row["id"],
        kind=row["kind"],
        run_at=row["run_at"],
        payload=json.loads(row["payload"]),
        attempts=row["attempts"],
        last_error=row["last_error"],
    )


class PostgresJobStore:
    name = "postgres"
    is_fake = False

    def __init__(self, db: Database) -> None:
        self._db = db

    async def put(self, job: Job) -> bool:
        status = await (await self._db.pool()).execute(
            "INSERT INTO jobs (id, kind, run_at, payload, attempts, last_error) "
            "VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT (id) DO NOTHING",
            job.id,
            job.kind,
            job.run_at,
            json.dumps(job.payload),
            job.attempts,
            job.last_error,
        )
        return bool(status.endswith(" 1"))

    async def claim(self, now: datetime, limit: int = 20) -> list[Job]:
        rows = await (await self._db.pool()).fetch(
            f"""
            UPDATE jobs SET locked_until = $2, attempts = attempts + 1
            WHERE id IN (
                SELECT id FROM jobs
                WHERE status = 'queued' AND run_at <= $1
                  AND (locked_until IS NULL OR locked_until <= $1)
                ORDER BY run_at, seq
                FOR UPDATE SKIP LOCKED
                LIMIT $3
            )
            RETURNING {_COLUMNS}
            """,
            now,
            now + LEASE,
            limit,
        )
        return sorted((_job(r) for r in rows), key=lambda j: j.run_at)

    async def complete(self, job_id: str) -> None:
        await (await self._db.pool()).execute("DELETE FROM jobs WHERE id = $1", job_id)

    async def retry(self, job_id: str, run_at: datetime, error: str) -> None:
        await (await self._db.pool()).execute(
            "UPDATE jobs SET run_at = $2, last_error = $3, locked_until = NULL WHERE id = $1",
            job_id,
            run_at,
            error,
        )

    async def fail(self, job_id: str, error: str) -> None:
        await (await self._db.pool()).execute(
            "UPDATE jobs SET status = 'failed', last_error = $2, locked_until = NULL WHERE id = $1",
            job_id,
            error,
        )

    async def next_run_at(self) -> datetime | None:
        value = await (await self._db.pool()).fetchval(
            "SELECT min(run_at) FROM jobs WHERE status = 'queued'"
        )
        return value  # type: ignore[no-any-return]

    async def failed(self) -> list[Job]:
        rows = await (await self._db.pool()).fetch(
            f"SELECT {_COLUMNS} FROM jobs WHERE status = 'failed' ORDER BY run_at, seq"
        )
        return [_job(r) for r in rows]
