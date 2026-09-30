# Stand-in for Workstream B - not part of the Part C deliverable
"""The next time a recurring reminder should fire (RFC 5545 RRULE), in the owner's wall-clock time.

"Every Monday at 08:00" means 08:00 on the owner's clock, so the rule is expanded on local
wall-clock times and only then turned back into an aware datetime. Across the Nov 1, 2026 change
(EDT -> EST) the UTC time moves from 12:00 to 13:00 while the owner still gets it at 08:00.

- Missed occurrences (the scheduler was off) are skipped: the next one is the first after `after`
  (normally "now"), so a restart never fires a burst of stale reminders.
- A wall-clock time that doesn't exist (02:30 on a spring-forward day) resolves with the
  pre-transition offset, i.e. it fires at 03:30 local that one day.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from dateutil.rrule import rrulestr


class InvalidRecurrence(ValueError):
    pass


def next_occurrence(
    rule: str, previous_due: datetime, tz: ZoneInfo, after: datetime | None = None
) -> datetime | None:
    """First occurrence strictly after `after` (default: `previous_due`), as UTC; None when the
    rule has run out (COUNT/UNTIL)."""
    start = previous_due.astimezone(tz).replace(tzinfo=None)  # the owner's wall clock
    try:
        recurrence = rrulestr(rule.removeprefix("RRULE:"), dtstart=start)
    except (ValueError, TypeError) as exc:
        raise InvalidRecurrence(f"can't read recurrence {rule!r}: {exc}") from exc
    threshold = max(previous_due, after or previous_due).astimezone(tz).replace(tzinfo=None)
    following = recurrence.after(threshold, inc=False)
    if following is None:
        return None
    return following.replace(tzinfo=tz).astimezone(UTC)
