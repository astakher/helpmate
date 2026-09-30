"""In-memory mail and calendar (HELPMATE_MAIL=fake, HELPMATE_CALENDAR=fake): what the app uses
until Google is connected, and what the tool tests run against. Nothing leaves the machine."""

from __future__ import annotations

import logging
from datetime import datetime

from helpmate.domain.models import CalendarEvent, EmailDraft, EmailSummary, new_id

log = logging.getLogger("helpmate.connectors")


class FakeMail:
    name = "fake"
    is_fake = True

    def __init__(self, inbox: list[EmailSummary] | None = None) -> None:
        self.inbox = inbox or []
        self.sent: list[EmailDraft] = []

    async def search(self, query: str, limit: int = 20) -> list[EmailSummary]:
        words = [w.lower() for w in query.split() if ":" not in w]  # ignore Gmail operators
        hits = [
            m
            for m in self.inbox
            if all(w in f"{m.sender} {m.subject} {m.snippet}".lower() for w in words)
        ]
        return sorted(hits, key=lambda m: m.received_at, reverse=True)[:limit]

    async def send(self, draft: EmailDraft) -> str:
        self.sent.append(draft)
        log.info("FAKE MAIL to %s: %s", ", ".join(draft.to), draft.subject)
        return new_id()


class FakeCalendar:
    name = "fake"
    is_fake = True

    def __init__(self, events: list[CalendarEvent] | None = None) -> None:
        self.events = events or []

    async def list_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        hits = [e for e in self.events if e.start < end and e.end > start]
        return sorted(hits, key=lambda e: e.start)

    async def create_event(self, event: CalendarEvent) -> CalendarEvent:
        created = event.model_copy(update={"id": event.id or new_id()})
        self.events.append(created)
        return created
