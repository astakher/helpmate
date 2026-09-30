# Stand-in for Workstream A - not part of the Part C deliverable
"""The owner's time words -> exact datetimes (agent/when.py)."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from helpmate.agent.when import UnclearTime, parse_when

TZ = ZoneInfo("America/Toronto")
MON_NOON = datetime(2026, 10, 5, 12, 0, tzinfo=TZ)
TUE_EVENING = datetime(2026, 9, 29, 20, 33, tzinfo=TZ)  # when the Sep 29 benchmark ran


def local(when) -> str:
    return when.due_at.astimezone(TZ).strftime("%a %Y-%m-%d %H:%M")


@pytest.mark.parametrize(
    ("words", "minutes"),
    [
        ("in 10 minutes", 10),
        ("in two hours", 120),
        ("in an hour", 60),
        ("in half an hour", 30),
        ("in an hour and a half", 90),
        ("in 45 mins", 45),
        ("20 minutes from now", 20),
        ("in 2 days", 2880),
        ("remind me in 3 hrs", 180),
    ],
)
def test_relative_times(words, minutes):
    assert parse_when(words, TUE_EVENING, TZ).due_at == TUE_EVENING + timedelta(minutes=minutes)


@pytest.mark.parametrize(
    ("words", "now", "expected"),
    [
        ("at 5pm", MON_NOON, "Mon 2026-10-05 17:00"),
        ("at 5pm", TUE_EVENING, "Wed 2026-09-30 17:00"),  # already past today -> tomorrow
        ("5:30 pm", MON_NOON, "Mon 2026-10-05 17:30"),
        ("at 17:00", MON_NOON, "Mon 2026-10-05 17:00"),
        ("at 5", MON_NOON, "Mon 2026-10-05 17:00"),  # no am/pm: whichever comes next
        ("at 9", MON_NOON, "Mon 2026-10-05 21:00"),
        ("tomorrow at 9am", MON_NOON, "Tue 2026-10-06 09:00"),
        ("tomorrow at noon", MON_NOON, "Tue 2026-10-06 12:00"),
        ("tomorrow", MON_NOON, "Tue 2026-10-06 09:00"),
        ("tonight", MON_NOON, "Mon 2026-10-05 20:00"),
        ("this evening", MON_NOON, "Mon 2026-10-05 18:00"),
        ("day after tomorrow at 8am", MON_NOON, "Wed 2026-10-07 08:00"),
        ("Friday at 3pm", MON_NOON, "Fri 2026-10-09 15:00"),
        ("on monday at 8am", MON_NOON, "Mon 2026-10-12 08:00"),  # 08:00 today has passed
        ("next wednesday", MON_NOON, "Wed 2026-10-07 09:00"),
        ("2026-10-06T09:00:00-04:00", MON_NOON, "Tue 2026-10-06 09:00"),
        ("2026-10-06T09:00", MON_NOON, "Tue 2026-10-06 09:00"),  # naive ISO = local time
    ],
)
def test_clock_and_calendar_words(words, now, expected):
    assert local(parse_when(words, now, TZ)) == expected


def test_repeats():
    weekly = parse_when("every Monday at 8am", MON_NOON, TZ)
    assert local(weekly) == "Mon 2026-10-12 08:00" and weekly.recurrence == "FREQ=WEEKLY;BYDAY=MO"
    daily = parse_when("every day at 7am", MON_NOON, TZ)
    assert local(daily) == "Tue 2026-10-06 07:00" and daily.recurrence == "FREQ=DAILY"
    weekdays = parse_when("weekdays at 6:45am", MON_NOON, TZ)
    assert weekdays.recurrence == "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"
    hinted = parse_when("8am", MON_NOON, TZ, weekday="thursday")  # the model's weekday field
    assert local(hinted) == "Thu 2026-10-08 08:00" and hinted.recurrence is None


def test_dst_change_keeps_wall_clock_time():
    saturday = datetime(2026, 10, 31, 12, 0, tzinfo=TZ)  # EDT; clocks go back on Sun Nov 1
    due = parse_when("tomorrow at 9am", saturday, TZ).due_at
    assert due.strftime("%Y-%m-%d %H:%M %z") == "2026-11-01 09:00 -0500"
    assert parse_when("in 24 hours", saturday, TZ).due_at - saturday == timedelta(hours=24)


@pytest.mark.parametrize("words", ["", "whenever", "soonish", "at 25:00", "at 13pm"])
def test_unclear_or_invalid_words_explain_what_to_send(words):
    with pytest.raises(UnclearTime) as exc:
        parse_when(words, MON_NOON, TZ)
    assert (
        words == "" or "isn't a valid time" in str(exc.value) or "in 10 minutes" in str(exc.value)
    )
