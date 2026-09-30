# Stand-in for Workstream B - not part of the Part C deliverable
"""Gmail + Google Calendar adapters against a mocked Google API (no network)."""

from __future__ import annotations

import base64
import email
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from helpmate.adapters.gcal import GoogleCalendar
from helpmate.adapters.gmail import GmailMail
from helpmate.adapters.google_oauth import GoogleApi, GoogleCredentials, GoogleNotConnected
from helpmate.domain.models import CalendarEvent, EmailDraft

TZ = ZoneInfo("America/Toronto")


class StubCredentials:
    def __init__(self) -> None:
        self.refreshes = 0

    async def token(self, force_refresh: bool = False) -> str:
        self.refreshes += force_refresh
        return f"token-{self.refreshes}"


def api(handler) -> tuple[GoogleApi, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(record))
    return GoogleApi(client, StubCredentials()), seen  # type: ignore[arg-type]


async def test_a_401_refreshes_the_token_once_and_retries():
    def handler(request):
        if request.headers["Authorization"] == "Bearer token-0":
            return httpx.Response(401)
        return httpx.Response(200, json={"ok": True})

    google, seen = api(handler)
    assert await google.request("GET", "https://example.test/x") == {"ok": True}
    assert [r.headers["Authorization"] for r in seen] == ["Bearer token-0", "Bearer token-1"]


async def test_a_403_says_how_to_fix_it():
    google, _ = api(
        lambda request: httpx.Response(403, json={"error": {"message": "API not enabled."}})
    )
    with pytest.raises(GoogleNotConnected, match="API not enabled"):
        await google.request("GET", "https://example.test/x")


async def test_missing_token_file_is_a_clear_error(tmp_path):
    with pytest.raises(GoogleNotConnected, match="google_auth.py"):
        await GoogleCredentials(tmp_path / "google_token.json").token()


async def test_gmail_search_reads_metadata_only():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/messages"):
            assert request.url.params["q"] == "from:bank is:unread"
            return httpx.Response(200, json={"messages": [{"id": "m1"}]})
        assert request.url.params["format"] == "metadata"  # never the body
        return httpx.Response(
            200,
            json={
                "id": "m1",
                "internalDate": "1791205200000",  # ms since the epoch
                "labelIds": ["INBOX", "UNREAD"],
                "snippet": "Your statement &amp; summary",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "Bank <no-reply@bank.example>"},
                        {"name": "Subject", "value": "October statement"},
                    ]
                },
            },
        )

    google, _ = api(handler)
    [found] = await GmailMail(google).search("from:bank is:unread", 5)
    assert found.sender == "Bank <no-reply@bank.example>"
    assert found.subject == "October statement"
    assert found.snippet == "Your statement & summary"
    assert found.unread
    assert found.received_at.tzinfo is not None


async def test_gmail_send_builds_a_proper_mime_message():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"id": "sent-1"})

    google, seen = api(handler)
    draft = EmailDraft(to=["jo@example.com"], cc=["sam@example.com"], subject="Hi", body="Line 1")
    assert await GmailMail(google).send(draft) == "sent-1"
    assert seen[0].url.path.endswith("/messages/send")
    message = email.message_from_bytes(base64.urlsafe_b64decode(captured["raw"]))
    assert (message["To"], message["Cc"], message["Subject"]) == (
        "jo@example.com",
        "sam@example.com",
        "Hi",
    )
    assert message.get_payload().strip() == "Line 1"


async def test_calendar_lists_timed_and_all_day_events_and_skips_cancelled():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["singleEvents"] == "true"
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "e1",
                        "summary": "Standup",
                        "start": {"dateTime": "2026-10-06T10:00:00-04:00"},
                        "end": {"dateTime": "2026-10-06T10:30:00-04:00"},
                    },
                    {
                        "id": "e2",
                        "summary": "Thanksgiving",
                        "start": {"date": "2026-10-12"},
                        "end": {"date": "2026-10-13"},
                    },
                    {"id": "e3", "status": "cancelled", "start": {}, "end": {}},
                ]
            },
        )

    google, _ = api(handler)
    start, end = datetime(2026, 10, 5, tzinfo=TZ), datetime(2026, 10, 19, tzinfo=TZ)
    standup, holiday = await GoogleCalendar(google, TZ).list_events(start, end)
    assert standup.title == "Standup" and standup.end.hour == 10 and standup.end.minute == 30
    assert holiday.start == datetime(2026, 10, 12, tzinfo=TZ)


async def test_calendar_create_sends_the_owners_timezone():
    sent = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent.update(json.loads(request.content))
        return httpx.Response(200, json={"id": "new", **sent})

    google, _ = api(handler)
    created = await GoogleCalendar(google, TZ).create_event(
        CalendarEvent(
            title="Dentist",
            start=datetime(2026, 10, 6, 15, 0, tzinfo=TZ),
            end=datetime(2026, 10, 6, 16, 0, tzinfo=TZ),
            location="Main St",
        )
    )
    assert sent["start"] == {"dateTime": "2026-10-06T15:00:00-04:00", "timeZone": TZ.key}
    assert sent["location"] == "Main St"
    assert created.id == "new" and created.title == "Dentist"
