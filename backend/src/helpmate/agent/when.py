# Stand-in for Workstream A - not part of the Part C deliverable
"""Turn the owner's time words into an exact datetime, in code instead of in the model.

Small models are unreliable at date arithmetic (the Sep 29 benchmark: "in 10 minutes" came back
as the duration "PT10M", "in two hours" as the wrong day). So the model copies the owner's words
into `when`, and this module does the maths, deterministically and DST-safely.

Understood (case-insensitive, combinable):
  in 10 minutes · in an hour · in half an hour · in two hours · in 3 days · 20 minutes from now
  at 5pm · 5:30 pm · 17:00 · noon · midnight · this morning/afternoon/evening · tonight
  today · tomorrow · day after tomorrow · (on|next) friday · every day/weekday · every monday
  Oct 12 · 12th of October · 2026-10-12
  an ISO 8601 datetime (a naive one is read as the owner's local time)
Anything else raises UnclearTime, whose message tells the model what to send instead.

For the calendar: parse_range() reads a period ("tomorrow afternoon", "Friday", "this week",
"next weekend", "the next 3 days") and parse_span() an event's start and end ("Friday 2 to 4pm",
"tomorrow at 3pm for 2 hours").
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
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
_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september",
           "october", "november", "december")  # fmt: skip
_MON = r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
_MON += r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
_DATE = re.compile(
    rf"\b(?P<mon>{_MON})\.? (?P<d>\d{{1,2}})(?:st|nd|rd|th)?\b"
    rf"|\b(?:the )?(?P<d2>\d{{1,2}})(?:st|nd|rd|th)? (?:of )?(?P<mon2>{_MON})\b"
    r"|\b(?P<y>\d{4})-(?P<m>\d{2})-(?P<d3>\d{2})\b"
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
    on_date = _calendar_date(phrase, now_local.date())
    if on_date is not None:
        day_offsets = [(on_date - now_local.date()).days]

    if hour is None and day_offsets is None and target_weekday is None and recurrence is None:
        raise UnclearTime(
            f"couldn't read a time from {raw!r}. Send the owner's words, e.g. {EXAMPLES}."
        )
    if hour is None:
        hour, minute, exact_hour = DEFAULT_HOUR, 0, True

    if target_weekday is not None and on_date is None:
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


def _calendar_date(phrase: str, today: date) -> date | None:
    """'Oct 12', 'the 12th of October', '2026-10-12' -> that date (next year's if it's past)."""
    match = _DATE.search(phrase)
    if match is None:
        return None
    try:
        if match["y"]:
            return date(int(match["y"]), int(match["m"]), int(match["d3"]))
        word = match["mon"] or match["mon2"]
        month = next(i for i, name in enumerate(_MONTHS, 1) if name.startswith(word[:3]))
        day = date(today.year, month, int(match["d"] or match["d2"]))
        return day if day >= today else day.replace(year=today.year + 1)
    except ValueError as exc:
        raise UnclearTime(f"{match[0]!r} isn't a real date") from exc


# --- Periods and event times (calendar tools) -----------------------------------------------

_DAY_PARTS = {"morning": (6, 12), "afternoon": (12, 17), "evening": (17, 22), "tonight": (17, 24)}
_NEXT_DAYS = re.compile(rf"\b(?:the )?(?:next|coming) (?P<n>{_NUM}|few|couple of) days\b")
RANGE_EXAMPLES = "'today', 'tomorrow afternoon', 'Friday', 'Oct 12', 'this week' or 'next week'"


def parse_range(words: str, now: datetime, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """A period in the owner's words -> (start, end) on whole local days, narrowed by a part of the
    day ("tomorrow afternoon"). Periods under way ("this week", "the next 3 days") start at today's
    midnight, so listing includes earlier events today; find_free_time skips the past itself."""
    phrase = " ".join(re.sub(r"[,;!?]", " ", words.lower()).split())
    today = now.astimezone(tz).date()
    monday = today - timedelta(days=today.weekday())

    def midnight(day: date) -> datetime:
        return datetime.combine(day, time(0), tzinfo=tz)

    if match := _NEXT_DAYS.search(phrase):
        n = {"few": 3, "couple of": 2}.get(match["n"]) or _number(match["n"])
        return midnight(today), midnight(today + timedelta(days=n + 1))
    if re.search(r"\bnext week\b", phrase):
        return midnight(monday + timedelta(days=7)), midnight(monday + timedelta(days=14))
    if re.search(r"\bweekend\b", phrase):
        saturday = monday + timedelta(days=5 + (7 if "next weekend" in phrase else 0))
        return midnight(max(today, saturday)), midnight(saturday + timedelta(days=2))
    if re.search(r"\bweek\b", phrase):  # this week, the rest of the week
        return midnight(today), midnight(monday + timedelta(days=7))
    if re.search(r"\bmonth\b", phrase):
        first = today.replace(day=1)
        following = (first + timedelta(days=32)).replace(day=1)
        if "next month" in phrase:
            return midnight(following), midnight((following + timedelta(days=32)).replace(day=1))
        return midnight(today), midnight(following)

    day = _calendar_date(phrase, today)
    if day is None and (offsets := _day_offsets(phrase)) is not None:
        day = today + timedelta(days=offsets[0])
    if day is None and (weekday := _WEEKDAY.search(phrase)):
        ahead = (WEEKDAYS.index(weekday["day"]) - today.weekday()) % 7
        day = today + timedelta(days=ahead or (7 if f"next {weekday['day']}" in phrase else 0))
    if day is None and any(re.search(rf"\b{part}\b", phrase) for part in _DAY_PARTS):
        day = today  # "this afternoon" is caught above; a bare "afternoon" means today's
    if day is None:
        raise UnclearTime(
            f"couldn't read a day or period from {words!r}. Send the owner's words, e.g. "
            f"{RANGE_EXAMPLES}."
        )
    for part, (first_hour, last_hour) in _DAY_PARTS.items():
        if re.search(rf"\b{part}\b", phrase):
            end = midnight(day + timedelta(days=1)) if last_hour == 24 else None
            return datetime.combine(day, time(first_hour), tzinfo=tz), end or datetime.combine(
                day, time(last_hour), tzinfo=tz
            )
    return midnight(day), midnight(day + timedelta(days=1))


_SPAN = re.compile(
    r"\b(?:from |between )?(?P<h1>\d{1,2})(?::(?P<m1>\d{2}))?\s*(?P<ap1>am|pm)?"
    r"\s*(?:-|–|to|until|till|and)\s*"
    r"(?P<h2>\d{1,2})(?::(?P<m2>\d{2}))?\s*(?P<ap2>am|pm)\b"
)
_FOR = re.compile(
    rf"\bfor (?:(?P<half>half an? hour)|(?P<n>{_NUM}) (?P<unit>min(?:ute)?s?|h(?:ou)?rs?)"
    r"(?P<andhalf> and a half)?)\b"
)


def parse_span(words: str, now: datetime, tz: ZoneInfo) -> tuple[datetime, datetime | None]:
    """An event's time -> (start, end). "Friday 2 to 4pm" and "at 3pm for 2 hours" give both;
    plain "tomorrow at 3pm" gives end None (the caller picks a length)."""
    phrase = words.lower().replace("a.m.", "am").replace("p.m.", "pm")
    phrase = " ".join(re.sub(r"[,;!?]", " ", phrase).split())
    if match := _SPAN.search(phrase):
        h1, m1, h2, m2 = (int(match[k] or 0) for k in ("h1", "m1", "h2", "m2"))
        if not (1 <= h1 <= 12 and 1 <= h2 <= 12 and m1 < 60 and m2 < 60):
            raise UnclearTime(f"{match[0]!r} isn't a valid time range")
        end_hour = h2 % 12 + (12 if match["ap2"] == "pm" else 0)
        start_hour = h1 % 12 + (12 if (match["ap1"] or match["ap2"]) == "pm" else 0)
        if not match["ap1"] and start_hour >= 12 and (start_hour, m1) >= (end_hour, m2):
            start_hour -= 12  # "11 to 1pm" starts at 11am
        start_words = f"at {start_hour % 12 or 12}:{m1:02d}{'am' if start_hour < 12 else 'pm'}"
        start = parse_when(
            f"{phrase[: match.start()]} {start_words} {phrase[match.end() :]}", now, tz
        )
        end = datetime.combine(start.due_at.date(), time(end_hour, m2), tzinfo=tz)
        if end <= start.due_at:
            raise UnclearTime(f"{match[0]!r} ends before it starts")
        return start.due_at, end
    length = None
    if match := _FOR.search(phrase):
        length = _relative_delta(match)
        phrase = f"{phrase[: match.start()]} {phrase[match.end() :]}"
    start = parse_when(phrase, now, tz).due_at
    return start, start + length if length else None
