# Stand-in for Workstream B - not part of the Part C deliverable
"""JobStore contract: every queue implementation must pass these (memory always; postgres when
HELPMATE_TEST_DATABASE_URL points at a THROWAWAY database, as in test_repositories.py)."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest

from helpmate.worker.jobs import LEASE, InMemoryJobStore, Job, JobStore

TEST_DATABASE_URL = os.environ.get("HELPMATE_TEST_DATABASE_URL", "")
NOW = datetime(2026, 10, 5, 16, 0, tzinfo=UTC)
_migrated = False


@pytest.fixture(params=["memory", "postgres"])
async def store(request) -> AsyncIterator[JobStore]:
    global _migrated
    if request.param == "memory":
        yield InMemoryJobStore()
        return
    if not TEST_DATABASE_URL:
        pytest.skip("set HELPMATE_TEST_DATABASE_URL to run the contract suite against Postgres")
    from helpmate.adapters.postgres_jobs import PostgresJobStore
    from helpmate.adapters.postgres_repos import PostgresRepositories

    repos = PostgresRepositories(TEST_DATABASE_URL)
    if not _migrated:
        await repos.migrate()
        _migrated = True
    await repos.truncate()
    yield PostgresJobStore(repos.db)
    await repos.close()


def job(job_id: str, minutes: int = 0, **payload) -> Job:
    return Job(id=job_id, kind="test", run_at=NOW + timedelta(minutes=minutes), payload=payload)


async def test_put_is_idempotent_by_id(store):
    assert await store.put(job("a", note="first"))
    assert not await store.put(job("a", note="second"))
    [claimed] = await store.claim(NOW)
    assert claimed.payload == {"note": "first"} and claimed.attempts == 1


async def test_only_due_jobs_are_claimed_oldest_first(store):
    await store.put(job("later", 5))
    await store.put(job("b", -1))
    await store.put(job("a", -2))
    assert [j.id for j in await store.claim(NOW)] == ["a", "b"]
    assert await store.next_run_at() == NOW - timedelta(minutes=2)  # leased ones still count


async def test_a_claimed_job_is_hidden_until_its_lease_ends(store):
    await store.put(job("a"))
    assert [j.id for j in await store.claim(NOW)] == ["a"]
    assert await store.claim(NOW + LEASE - timedelta(seconds=1)) == []
    [again] = await store.claim(NOW + LEASE)  # the worker died: someone else takes it
    assert again.attempts == 2


async def test_concurrent_claims_never_share_a_job(store):
    for i in range(10):
        await store.put(job(f"j{i}"))
    first, second = await asyncio.gather(store.claim(NOW, limit=6), store.claim(NOW, limit=6))
    ids = [j.id for j in first + second]
    assert len(ids) == len(set(ids)) == 10


async def test_retry_moves_the_job_and_complete_removes_it(store):
    await store.put(job("a"))
    await store.claim(NOW)
    await store.retry("a", NOW + timedelta(minutes=2), "push failed")
    assert await store.claim(NOW + timedelta(minutes=1)) == []
    [retried] = await store.claim(NOW + timedelta(minutes=2))
    assert (retried.attempts, retried.last_error) == (2, "push failed")
    await store.complete("a")
    assert await store.claim(NOW + timedelta(hours=1)) == []
    assert await store.next_run_at() is None
    assert await store.put(job("a"))  # a finished job's id can be queued again


async def test_failed_jobs_are_kept_but_never_claimed(store):
    await store.put(job("a"))
    await store.claim(NOW)
    await store.fail("a", "gave up")
    assert await store.claim(NOW + timedelta(days=1)) == []
    assert [(j.id, j.last_error) for j in await store.failed()] == [("a", "gave up")]
    assert not await store.put(job("a"))  # and it isn't silently re-queued
    assert await store.next_run_at() is None
