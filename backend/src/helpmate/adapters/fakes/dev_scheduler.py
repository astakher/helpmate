"""DevScheduler (HELPMATE_SCHEDULER=dev): the JobScheduler on an in-memory queue.

Same behaviour as HELPMATE_SCHEDULER=pg (worker/scheduler.py: one job per reminder occurrence,
retries with backoff, wakes for the next due job, recurring reminders on the owner's wall clock),
except that queued retries are lost on restart. Due reminders still fire after a restart: every
tick sweeps the reminders repository.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

from helpmate.domain.ports import Clock, NotifierPort, Repositories
from helpmate.worker.jobs import InMemoryJobStore
from helpmate.worker.scheduler import JobScheduler


class DevScheduler(JobScheduler):
    def __init__(
        self,
        repos: Repositories,
        notifier: NotifierPort,
        clock: Clock,
        tick_seconds: float = 5.0,  # kept for callers; the loop now sleeps until the next job
        tz: ZoneInfo | None = None,
    ) -> None:
        super().__init__(InMemoryJobStore(), repos, notifier, clock, tz, name="dev", is_fake=True)
