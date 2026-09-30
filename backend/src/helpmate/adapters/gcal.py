# Stand-in for Workstream B - not part of the Part C deliverable
"""Google Calendar (HELPMATE_CALENDAR=google), primary calendar, over the REST API
(calendar.events). create_event() runs only after the owner approves the event card.
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from helpmate.adapters.google_oauth import GoogleApi
from helpmate.domain.models import CalendarEvent

CALENDAR = "https://www.googleapis.com/calendar/v3/calendars/primary"


class GoogleCalendar:
    name = "google"
    is_fake = False

    def __init__(self, api: GoogleApi, tz: ZoneInfo) -> None:
        self._api = api
        self._tz = tz

    async def list_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        data = await self._api.request(
            "GET",
            f"{CALENDAR}/events",
            params={
                "timeMin": start.astimezone(UTC).isoformat(),
                "timeMax": end.astimezone(UTC).isoformat(),
                "singleEvents": "true",  # expand recurring events into their occurrences
                "orderBy": "startTime",
                "maxResults": 250,
            },
        )
        return [
            self._event(item)
            for item in data.get("items", [])
            if item.get("status") != "cancelled" and item.get("transparency") != "transparent"
        ]

    async def create_event(self, event: CalendarEvent) -> CalendarEvent:
        body: dict[str, Any] = {
            "summary": event.title,
            "start": {"dateTime": event.start.isoformat(), "timeZone": self._tz.key},
            "end": {"dateTime": event.end.isoformat(), "timeZone": self._tz.key},
        }
        if event.location:
            body["location"] = event.location
        if event.description:
            body["description"] = event.description
        return self._event(await self._api.request("POST", f"{CALENDAR}/events", json=body))

    def _event(self, item: dict[str, Any]) -> CalendarEvent:
        return CalendarEvent(
            id=item.get("id"),
            title=item.get("summary") or "(busy)",
            start=self._when(item["start"]),
            end=self._when(item["end"]),
            location=item.get("location"),
            description=item.get("description"),
        )

    def _when(self, value: dict[str, str]) -> datetime:
        if "dateTime" in value:
            return datetime.fromisoformat(value["dateTime"])
        day = datetime.fromisoformat(value["date"]).date()  # all-day event: local midnight
        return datetime.combine(day, time(0), tzinfo=self._tz)
