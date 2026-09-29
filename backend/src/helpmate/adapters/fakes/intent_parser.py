"""A tiny rule-based intent parser used by the ScriptedAgent fake.

This is not natural-language understanding. It recognises a handful of phrases so the approval
flow can be demoed end to end before the real agent loop (Workstream A) plugs in:

  remind me to <what> in <n> seconds|minutes|hours
  remind me to <what> [today|tomorrow] at <h>[:mm][am|pm] [today|tomorrow]
  add task <title> [this week|this term|this year|someday]
  what are my reminders / list my reminders
"""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from helpmate.domain.models import ToolCall, new_id

_REMIND_IN = re.compile(
    r"^remind me (?:to )?(?P<what>.+?) in (?P<n>\d+) ?"
    r"(?P<unit>seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h)$",
    re.IGNORECASE,
)
_REMIND_AT = re.compile(
    r"^remind me (?:to )?(?P<what>.+?) (?:(?P<day1>today|tomorrow) )?at "
    r"(?P<h>\d{1,2})(?::(?P<m>\d{2}))? ?(?P<ampm>am|pm)?(?: (?P<day2>today|tomorrow))?$",
    re.IGNORECASE,
)
_ADD_TASK = re.compile(
    r"^(?:add|create) (?:a )?task(?: to)?:? (?P<title>.+?)"
    r"(?: (?P<horizon>this week|this term|this year|someday))?$",
    re.IGNORECASE,
)
_LIST_REMINDERS = re.compile(r"^(?:what are|list|show)(?: me)? my reminders$", re.IGNORECASE)

_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600}
_HORIZONS = {"this week": "week", "this term": "term", "this year": "year", "someday": "someday"}


def parse_intent(text: str, now: datetime, tz: ZoneInfo) -> ToolCall | None:
    phrase = " ".join(text.split()).rstrip(".!?").strip()

    if match := _REMIND_IN.match(phrase):
        seconds = int(match["n"]) * _UNIT_SECONDS[match["unit"][0].lower()]
        due = now + timedelta(seconds=seconds)
        return _call("create_reminder", text=match["what"], due_at=due.isoformat())

    if match := _REMIND_AT.match(phrase):
        day = (match["day1"] or match["day2"] or "").lower() or None
        due = _next_local_time(
            now.astimezone(tz), int(match["h"]), int(match["m"] or 0), match["ampm"], day, tz
        )
        if due is not None:
            return _call("create_reminder", text=match["what"], due_at=due.isoformat())

    if match := _ADD_TASK.match(phrase):
        horizon = _HORIZONS[(match["horizon"] or "this week").lower()]
        return _call("create_task", title=match["title"], horizon=horizon)

    if _LIST_REMINDERS.match(phrase):
        return _call("list_reminders")

    return None


def _next_local_time(
    now_local: datetime, hour: int, minute: int, ampm: str | None, day: str | None, tz: ZoneInfo
) -> datetime | None:
    if ampm:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if ampm.lower() == "pm" else 0)
    if hour > 23 or minute > 59:
        return None
    # "at 5" with no am/pm: take whichever of 05:00 / 17:00 comes next
    hours = [hour] if (ampm or hour == 0 or hour >= 12) else [hour, hour + 12]
    days = {"today": [0], "tomorrow": [1]}.get(day or "", [0, 1])
    candidates = [
        # combine() on the local calendar date keeps wall-clock time correct across DST changes
        datetime.combine(now_local.date() + timedelta(days=d), time(h, minute), tzinfo=tz)
        for d in days
        for h in hours
    ]
    upcoming = [c for c in candidates if c > now_local]
    return upcoming[0] if upcoming else (candidates[0] if day else None)


def _call(name: str, **arguments: object) -> ToolCall:
    return ToolCall(id=new_id(), name=name, arguments=arguments)
