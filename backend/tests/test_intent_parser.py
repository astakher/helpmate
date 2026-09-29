from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from helpmate.adapters.fakes.intent_parser import parse_intent

TZ = ZoneInfo("America/Toronto")
NOON = datetime(2026, 10, 5, 12, 0, tzinfo=TZ)  # Monday, EDT (UTC-4)


def _due(text: str, now: datetime = NOON) -> datetime:
    call = parse_intent(text, now.astimezone(UTC), TZ)
    assert call is not None and call.name == "create_reminder", text
    return datetime.fromisoformat(call.arguments["due_at"]).astimezone(TZ)


def test_relative_time():
    assert _due("remind me to call mom in 2 minutes") == NOON + timedelta(minutes=2)
    assert _due("Remind me to stretch in 30 seconds.") == NOON + timedelta(seconds=30)
    assert _due("remind me to leave in 1 hour") == NOON + timedelta(hours=1)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("remind me to call mom at 5pm", datetime(2026, 10, 5, 17, 0, tzinfo=TZ)),
        ("remind me to call mom at 5", datetime(2026, 10, 5, 17, 0, tzinfo=TZ)),  # next of 5/17
        ("remind me to take meds at 9am", datetime(2026, 10, 6, 9, 0, tzinfo=TZ)),  # 9am passed
        ("remind me to submit tomorrow at 9:30am", datetime(2026, 10, 6, 9, 30, tzinfo=TZ)),
        ("remind me to run at 18:45", datetime(2026, 10, 5, 18, 45, tzinfo=TZ)),
    ],
)
def test_clock_time(text, expected):
    assert _due(text) == expected


def test_wall_clock_is_kept_across_the_dst_change():
    # Saturday Oct 31 2026 is EDT (UTC-4); DST ends Sunday Nov 1 at 02:00 -> EST (UTC-5).
    saturday_evening = datetime(2026, 10, 31, 20, 0, tzinfo=TZ)
    due = _due("remind me to wake up tomorrow at 9am", saturday_evening)
    assert due == datetime(2026, 11, 1, 9, 0, tzinfo=TZ)
    assert due.astimezone(UTC).hour == 14  # 09:00 EST, not 13:00 UTC


def test_tasks_and_listing():
    task = parse_intent("add task read chapter 3 this term", NOON, TZ)
    assert task is not None and task.name == "create_task"
    assert task.arguments == {"title": "read chapter 3", "horizon": "term"}
    default = parse_intent("add task buy milk", NOON, TZ)
    assert default is not None and default.arguments["horizon"] == "week"
    listing = parse_intent("what are my reminders?", NOON, TZ)
    assert listing is not None and listing.name == "list_reminders"


@pytest.mark.parametrize("text", ["hello", "remind me", "remind me to x at 25pm", ""])
def test_everything_else_is_not_an_intent(text):
    assert parse_intent(text, NOON, TZ) is None
