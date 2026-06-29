"""Time parsing and formatting for user-facing tool parameters.

Tools accept natural language ("tomorrow 3pm", "in 2 hours", "next Tuesday"),
date-only strings ("2026-04-20"), or full ISO 8601. This module resolves any
of those to a concrete datetime in the user's timezone and returns both the
machine value (for the API) and a human label (for response summaries).

Policy:
- Relative terms always resolve to the nearest future occurrence.
- Date-only strings resolve to 09:00 local time (start of working day).
- Naive datetimes are interpreted in the user's timezone.
- The returned ISO string always includes an offset, never a bare 'Z',
  unless the caller explicitly requests UTC normalization.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import dateparser

DEFAULT_DAY_START_HOUR = 9


@dataclass(frozen=True)
class ResolvedTime:
    """A time value resolved from user input.

    Attributes:
        dt: The concrete datetime, always timezone-aware.
        iso: ISO 8601 string with offset (e.g., '2026-04-20T09:00:00-07:00').
        iso_utc: ISO 8601 string in UTC with 'Z' suffix.
        label: Human-friendly label ('Saturday, April 18 at 3:00 PM PDT').
        input: The original user input, preserved for debugging.
    """

    dt: datetime
    iso: str
    iso_utc: str
    label: str
    input: str


class TimeParseError(ValueError):
    """Raised when a user-supplied time string cannot be resolved."""


_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_when(
    value: str,
    *,
    tz: str,
    now: Optional[datetime] = None,
    day_start_hour: int = DEFAULT_DAY_START_HOUR,
) -> ResolvedTime:
    """Resolve a user-supplied time string to a concrete datetime.

    Args:
        value: ISO 8601, YYYY-MM-DD, or natural language.
        tz: IANA timezone name (e.g., 'America/Los_Angeles'). Used to
            interpret naive input and build the output.
        now: Reference time for relative terms. Defaults to current time
            in the supplied tz. Tests can pin this.
        day_start_hour: Hour (0-23) used when only a date is supplied.

    Returns:
        ResolvedTime.

    Raises:
        TimeParseError: If the input cannot be resolved.
    """
    if not value or not value.strip():
        raise TimeParseError("empty time value")

    zone = ZoneInfo(tz)
    reference = now or datetime.now(zone)
    stripped = value.strip()

    dt = _try_iso(stripped, zone) or _try_date_only(stripped, zone, day_start_hour)

    if dt is None:
        dt = _try_natural(stripped, zone, reference)
        if dt is not None and _is_date_only_phrase(stripped) and _has_inherited_time(dt, reference):
            dt = dt.replace(hour=day_start_hour, minute=0, second=0, microsecond=0)

    if dt is None:
        raise TimeParseError(
            f"could not understand time '{value}'. "
            "Try ISO format ('2026-04-20T15:00:00-07:00'), "
            "date-only ('2026-04-20'), or natural language ('tomorrow at 3pm')."
        )

    return _build_resolved(dt, stripped, zone)


def _is_date_only_phrase(value: str) -> bool:
    """True if the NL input looks like a date without a time-of-day component."""
    lowered = value.lower()
    if re.search(r"\d+\s*(:|am|pm|a\.m\.|p\.m\.|h|hours?|minutes?|min|mins)", lowered):
        return False
    if any(tok in lowered for tok in ("noon", "midnight", "morning", "afternoon", "evening", "night")):
        return False
    return True


def _has_inherited_time(dt: datetime, reference: datetime) -> bool:
    """True if the resolved time appears to be inherited from the reference.

    dateparser returns either 00:00:00 (fresh parse) or the reference time-of-day
    (when the input has no explicit time). Either signals 'user supplied a date
    only' and we should apply day_start_hour.
    """
    ref = reference.astimezone(dt.tzinfo) if reference.tzinfo else reference
    if dt.hour == 0 and dt.minute == 0 and dt.second == 0:
        return True
    return dt.hour == ref.hour and dt.minute == ref.minute and dt.second == ref.second


def parse_date(
    value: str,
    *,
    tz: str,
    now: Optional[datetime] = None,
) -> str:
    """Resolve a user input to a YYYY-MM-DD string in the user's timezone.

    Used for tools whose underlying Reclaim endpoint requires date-only.
    """
    resolved = parse_when(value, tz=tz, now=now)
    return resolved.dt.strftime("%Y-%m-%d")


def parse_range(
    when: str,
    *,
    tz: str,
    now: Optional[datetime] = None,
) -> tuple[str, str]:
    """Resolve a natural-language range to (start_date, end_date) YYYY-MM-DD.

    Accepts: 'today', 'tomorrow', 'this week', 'next week', 'this month',
    'next 7 days', or an explicit 'YYYY-MM-DD..YYYY-MM-DD' range. Falls back
    to treating the input as a single date (start == end).
    """
    zone = ZoneInfo(tz)
    reference = (now or datetime.now(zone)).astimezone(zone)
    stripped = when.strip().lower()

    if ".." in when:
        parts = [p.strip() for p in when.split("..", 1)]
        if len(parts) == 2 and all(parts):
            return parse_date(parts[0], tz=tz, now=now), parse_date(parts[1], tz=tz, now=now)

    today = reference.date()

    if stripped in {"today"}:
        return today.isoformat(), today.isoformat()
    if stripped in {"tomorrow"}:
        d = today + timedelta(days=1)
        return d.isoformat(), d.isoformat()
    if stripped in {"yesterday"}:
        d = today - timedelta(days=1)
        return d.isoformat(), d.isoformat()
    if stripped in {"this week"}:
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        return start.isoformat(), end.isoformat()
    if stripped in {"next week"}:
        start = today - timedelta(days=today.weekday()) + timedelta(days=7)
        end = start + timedelta(days=6)
        return start.isoformat(), end.isoformat()
    if stripped in {"last week"}:
        start = today - timedelta(days=today.weekday()) - timedelta(days=7)
        end = start + timedelta(days=6)
        return start.isoformat(), end.isoformat()
    if stripped in {"this month"}:
        start = today.replace(day=1)
        next_month = (start + timedelta(days=32)).replace(day=1)
        end = next_month - timedelta(days=1)
        return start.isoformat(), end.isoformat()
    m = re.match(r"next\s+(\d+)\s+days?", stripped)
    if m:
        n = int(m.group(1))
        return today.isoformat(), (today + timedelta(days=n)).isoformat()

    single = parse_date(when, tz=tz, now=now)
    return single, single


def _try_iso(value: str, zone: ZoneInfo) -> Optional[datetime]:
    if not _ISO_RE.match(value):
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=zone)
    return dt


def _try_date_only(value: str, zone: ZoneInfo, day_start_hour: int) -> Optional[datetime]:
    if not _DATE_RE.match(value):
        return None
    try:
        d = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None
    return d.replace(hour=day_start_hour, tzinfo=zone)


_WEEKDAYS = {
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
    "mon",
    "tue",
    "tues",
    "wed",
    "thu",
    "thur",
    "thurs",
    "fri",
    "sat",
    "sun",
}


_PART_OF_DAY = {
    "morning": "9am",
    "afternoon": "2pm",
    "evening": "6pm",
    "night": "9pm",
    "noon": "12pm",
    "midnight": "12am",
}

_TONIGHT_ALIAS = "today 9pm"


def _expand_part_of_day(value: str) -> str:
    """Replace vague time-of-day words with concrete clock times.

    'tomorrow morning' -> 'tomorrow 9am'. Standalone 'tonight' becomes
    'today 9pm' so dateparser has a date anchor.
    """
    # 'tonight at 11pm' -> 'today at 11pm'; standalone 'tonight' -> 'today 9pm'.
    out = re.sub(
        r"\btonight\b(\s+at\s+\d)",
        lambda m: "today" + m.group(1),
        value,
        flags=re.IGNORECASE,
    )
    out = re.sub(r"\btonight\b", _TONIGHT_ALIAS, out, flags=re.IGNORECASE)
    # 'this evening' / 'this morning' -> 'today <clock>'.
    for word, clock in _PART_OF_DAY.items():
        out = re.sub(rf"\bthis\s+{word}\b", f"today {clock}", out, flags=re.IGNORECASE)
        out = re.sub(rf"\b{word}\b", clock, out, flags=re.IGNORECASE)
    return out


def _try_natural(value: str, zone: ZoneInfo, reference: datetime) -> Optional[datetime]:
    settings = {
        "TIMEZONE": str(zone),
        "RETURN_AS_TIMEZONE_AWARE": True,
        "PREFER_DATES_FROM": "future",
        "RELATIVE_BASE": reference,
    }
    expanded = _expand_part_of_day(value)
    parsed = dateparser.parse(expanded, settings=settings)

    if parsed is None:
        # dateparser returns None for "next <weekday>" under PREFER_DATES_FROM=future.
        # Strip leading "next " when the remainder is a weekday — bare "<weekday>"
        # already resolves to the next occurrence.
        lowered = value.lower().strip()
        if lowered.startswith("next "):
            rest = _expand_part_of_day(lowered[5:].strip())
            first_word = rest.split()[0] if rest else ""
            if first_word in _WEEKDAYS:
                parsed = dateparser.parse(rest, settings=settings)

    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    return parsed.astimezone(zone)


def _build_resolved(dt: datetime, original: str, zone: ZoneInfo) -> ResolvedTime:
    local = dt.astimezone(zone)
    iso = local.isoformat()
    iso_utc = local.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
    label = _humanize(local)
    return ResolvedTime(dt=local, iso=iso, iso_utc=iso_utc, label=label, input=original)


def _humanize(dt: datetime) -> str:
    """Render a datetime for user-facing summaries.

    Examples:
        'Monday, April 20 at 9:00 AM PDT'
        'April 20, 2027 at 3:30 PM PST' (when year is not current)
    """
    now = datetime.now(dt.tzinfo)
    if dt.year == now.year:
        return dt.strftime("%A, %B %-d at %-I:%M %p %Z").strip()
    return dt.strftime("%B %-d, %Y at %-I:%M %p %Z").strip()
