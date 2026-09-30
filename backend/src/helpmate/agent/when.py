# Stand-in for Workstream A - not part of the Part C deliverable
"""Turn the owner's time words into an exact datetime, in code instead of in the model.

Small models are unreliable at date arithmetic (the Sep 29 benchmark: "in 10 minutes" came back
as the duration "PT10M", "in two hours" as the wrong day). So the model copies the owner's words
into `when`, and this module does the maths, deterministically and DST-safely.

Understood (case-insensitive, combinable):
  in 10 minutes · in an hour · in half an hour · in two hours · in 3 days · 20 minutes from now
  at 5pm · 5:30 pm · 17:00 · noon · midnight · this morning/afternoon/evening · tonight
  today · tomorrow · day after tomorrow · (on|next) friday · every day/weekday · every monday
  an ISO 8601 datetime (a naive one is read as the owner's local time)
Anything else raises UnclearTime, whose message tells the model what to send instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo


class UnclearTime(ValueError):
    pass


@dataclass(frozen=True)
class When:
    due_at: datetime  # timezone-aware, in the owner's zone
    recurrence: str | None = None  # RFC 5545 RRULE when the words say "every …"


WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
RRULE_DAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
_NUMBERS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten "
                                       "eleven twelve".split())}  # fmt: skip
_NUMBERS |= {"a": 1, "an": 1, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40,
             "forty-five": 45, "fifty": 50, "sixty": 60, "ninety": 90}  # fmt: skip
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 7 * 86400}  # by first letter
_PARTS_OF_DAY = {"morning": 9, "afternoon": 15, "evening": 18, "night": 20, "tonight": 20}
DEFAULT_HOUR = 9  # a day with no time ("tomorrow") means 09:00

_NUM = r"\d+|" + "|".join(sorted(_NUMBERS, key=len, reverse=True))
_UNIT = r"sec(?:ond)?s?|min(?:ute)?s?|h(?:ou)?rs?|days?|weeks?"
_RELATIVE = re.compile(
    rf"\bin (?:(?P<half>half an? hour)|(?P<n>{_NUM}) (?P<unit>{_UNIT})(?P<andhalf> and a half)?)\b"
    rf"|\b(?P<n2>{_NUM}) (?P<unit2>{_UNIT}) from now\b"
)
_CLOCK = re.compile(
    r"\b(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ampm>a\.?m\.?|p\.?m\.?)(?![a-z])"
    r"|\b(?P<h24>\d{1,2}):(?P<m24>\d{2})\b"
    r"|\bat (?P<hat>\d{1,2})\b(?!:)"
)
_WEEKDAY = re.compile(
    r"\b(?P<every>every |each )?(?:on |next |this )?(?P<day>" + "|".join(WEEKDAYS) + r")s?\b"
)
EXAMPLES = "'in 10 minutes', 'at 5pm', 'tomorrow at 9am', 'Friday at 3pm' or 'every Monday at 8am'"


def parse_when(words: str, now: datetime, tz: ZoneInfo, weekday: str | None = None) -> When:
    """`weekday` is a hint from the model's separate `weekday` field (for "every Monday")."""
    raw = words.strip()
    if not raw:
        raise UnclearTime(f"`when` is empty. Copy the owner's time words, e.g. {EXAMPLES}.")
    iso = _iso(raw, tz)
    if iso is not None:
        return When(iso)

    phrase = " ".join(re.sub(r"[,;!?]", " ", raw.lower()).split())
    now_local = now.astimezone(tz)

    if match := _RELATIVE.search(phrase):
        return When(now_local + _relative_delta(match))

    recurrence = None
    if re.search(r"\b(every|each) day\b|\bdaily\b|\bevery (morning|evening|night)\b", phrase):
        recurrence = "FREQ=DAILY"
    elif re.search(r"\b(every|each) weekday\b|\bweekdays\b", phrase):
        recurrence = "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"

    day_match = _WEEKDAY.search(phrase)
    target_weekday = day_match["day"] if day_match else (weekday.lower() if weekday else None)
    if target_weekday not in (None, *WEEKDAYS):
        raise UnclearTime(f"unknown weekday {weekday!r}")
    if day_match and day_match["every"]:
        recurrence = f"FREQ=WEEKLY;BYDAY={RRULE_DAYS[WEEKDAYS.index(target_weekday)]}"

    hour, minute, exact_hour = _clock(phrase)
    day_offsets = _day_offsets(phrase)

    if hour is None and day_offsets is None and target_weekday is None and recurrence is None:
        raise UnclearTime(
            f"couldn't read a time from {raw!r}. Send the owner's words, e.g. {EXAMPLES}."
        )
    if hour is None:
        hour, minute, exact_hour = DEFAULT_HOUR, 0, True

    if target_weekday is not None:
        ahead = (WEEKDAYS.index(target_weekday) - now_local.weekday()) % 7
        day_offsets = [ahead, ahead + 7]
    elif day_offsets is None:
        day_offsets = [0, 1]  # a bare time means its next occurrence

    hours = [hour] if exact_hour else [hour, hour + 12]  # "at 5": whichever of 05:00/17:00 is next
    candidates = sorted(
        # combine() on the local calendar date keeps wall-clock time right across DST changes
        datetime.combine(now_local.date() + timedelta(days=d), time(h, minute), tzinfo=tz)
        for d in day_offsets
        for h in hours
    )
    upcoming = [c for c in candidates if c > now_local]
    if not upcoming:
        raise UnclearTime(f"{raw!r} is in the past. Ask the owner for a future time.")
    return When(upcoming[0], recurrence)


def _iso(raw: str, tz: ZoneInfo) -> datetime | None:
    if not re.match(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", raw):
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=tz)).astimezone(tz)


def _number(token: str) -> int:
    return int(token) if token.isdigit() else _NUMBERS[token]


def _relative_delta(match: re.Match[str]) -> timedelta:
    if match["half"]:
        return timedelta(minutes=30)
    n, unit = (match["n"], match["unit"]) if match["n"] else (match["n2"], match["unit2"])
    base = _UNIT_SECONDS[unit[0]]
    return timedelta(seconds=_number(n) * base + (base // 2 if match["andhalf"] else 0))


def _clock(phrase: str) -> tuple[int | None, int, bool]:
    """-> (hour 0-23, minute, exact). `exact` is False for a bare "at 5" (could be am or pm)."""
    if re.search(r"\bnoon\b|\bmidday\b", phrase):
        return 12, 0, True
    if re.search(r"\bmidnight\b", phrase):
        return 0, 0, True
    if match := _CLOCK.search(phrase):
        if match["ampm"]:
            hour, minute = int(match["h"]), int(match["m"] or 0)
            if not 1 <= hour <= 12 or minute > 59:
                raise UnclearTime(f"{match[0]!r} isn't a valid time")
            return hour % 12 + (12 if match["ampm"].startswith("p") else 0), minute, True
        if match["h24"]:
            hour, minute = int(match["h24"]), int(match["m24"])
            if hour > 23 or minute > 59:
                raise UnclearTime(f"{match[0]!r} isn't a valid time")
            return hour, minute, hour == 0 or hour >= 12
        hour = int(match["hat"])
        if hour > 23:
            raise UnclearTime(f"{match[0]!r} isn't a valid time")
        return hour, 0, hour == 0 or hour >= 12
    for part, hour in _PARTS_OF_DAY.items():
        if re.search(rf"\b{part}\b", phrase):
            return hour, 0, True
    return None, 0, True


def _day_offsets(phrase: str) -> list[int] | None:
    if re.search(r"\bday after tomorrow\b", phrase):
        return [2]
    if re.search(r"\btomorrow\b", phrase):
        return [1]
    if re.search(r"\btoday\b|\btonight\b|\bthis (morning|afternoon|evening)\b", phrase):
        return [0]
    return None
