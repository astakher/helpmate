"""In-memory mail and calendar (HELPMATE_MAIL=fake, HELPMATE_CALENDAR=fake): what the app uses
until Google is connected, and what the tool tests run against. Nothing leaves the machine."""

from __future__ import annotations

import logging
from datetime import datetime

from helpmate.domain.models import CalendarEvent, EmailDetail, EmailDraft, EmailSummary, new_id

log = logging.getLogger("helpmate.connectors")


class FakeMail:
    name = "fake"
    is_fake = True

    def __init__(self, inbox: list[EmailSummary] | None = None) -> None:
        self.inbox = inbox or []
        self.bodies: dict[str, str] = {}  # message id -> full text (default: its snippet)
        self.sent: list[EmailDraft] = []

    async def read(self, message_id: str) -> EmailDetail | None:
        summary = next((m for m in self.inbox if m.id == message_id), None)
        if summary is None:
            return None
        return EmailDetail(
            id=summary.id,
            thread_id=f"thread-{summary.id}",
            sender=summary.sender,
            subject=summary.subject,
            body=self.bodies.get(summary.id, summary.snippet),
            message_id=f"<{summary.id}@fake.example>",
            received_at=summary.received_at,
            labels=summary.labels,
        )

    async def search(self, query: str, limit: int = 20) -> list[EmailSummary]:
        terms = query.lower().split()
        words = [w for w in terms if ":" not in w]  # other Gmail operators are ignored
        hits = [
            m
            for m in self.inbox
            if all(w in f"{m.sender} {m.subject} {m.snippet}".lower() for w in words)
            and (m.unread or "is:unread" not in terms)
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
