"""Context tool — the anchor call every time-dependent flow should start with.

Returns the user's current time, timezone, working hours today, active timer,
and quick task counts in a single call. Claude calls this once at the start of
any scheduling flow so it doesn't have to invent dates from its training cutoff.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastmcp.exceptions import ToolError

from reclaim_mcp.cache import ttl_cache
from reclaim_mcp.client import ReclaimClient
from reclaim_mcp.config import get_settings
from reclaim_mcp.exceptions import RateLimitError, ReclaimError


def _get_client() -> ReclaimClient:
    settings = get_settings()
    return ReclaimClient(settings)


def _system_tz() -> str:
    """System timezone name, falling back to UTC on older platforms."""
    try:
        import time

        tz_name = time.tzname[time.daylight] if time.daylight else time.tzname[0]
        ZoneInfo(tz_name)
        return tz_name
    except (ZoneInfoNotFoundError, LookupError, AttributeError, IndexError):
        return "UTC"


def _extract_tz_from_timeschemes(timeschemes: Any) -> Optional[str]:
    """Pull an IANA timezone name from a /api/timeschemes response.

    The endpoint returns a list of scheme objects with a nested schedule. The
    timezone lives either at the top level of a scheme or under its schedule.
    We try a few likely keys and validate each against zoneinfo before
    returning.
    """
    if not isinstance(timeschemes, list):
        return None
    for scheme in timeschemes:
        if not isinstance(scheme, dict):
            continue
        for key in ("timezone", "timeZone", "tz", "timeZoneId"):
            candidate = scheme.get(key)
            if isinstance(candidate, str) and candidate:
                try:
                    ZoneInfo(candidate)
                    return candidate
                except ZoneInfoNotFoundError:
                    continue
        schedule = scheme.get("schedule") or {}
        if isinstance(schedule, dict):
            for key in ("timezone", "timeZone", "tz"):
                candidate = schedule.get(key)
                if isinstance(candidate, str) and candidate:
                    try:
                        ZoneInfo(candidate)
                        return candidate
                    except ZoneInfoNotFoundError:
                        continue
    return None


def _working_hours_for_today(timeschemes: Any, weekday_name: str) -> Optional[dict[str, Any]]:
    """Extract today's working hours (start, end) from a timeschemes payload.

    Returns None if the API shape is unexpected or today has no working window.
    """
    if not isinstance(timeschemes, list) or not timeschemes:
        return None
    # Prefer a scheme marked as default/primary; otherwise first.
    scheme = next(
        (s for s in timeschemes if isinstance(s, dict) and (s.get("primary") or s.get("default"))),
        timeschemes[0] if isinstance(timeschemes[0], dict) else None,
    )
    if not isinstance(scheme, dict):
        return None
    hours = scheme.get("hours") or scheme.get("dailyHours") or {}
    schedule = scheme.get("schedule") or {}
    if isinstance(schedule, dict):
        hours = schedule.get("hours") or hours
    if not isinstance(hours, dict):
        return None
    day_entry = hours.get(weekday_name) or hours.get(weekday_name.lower())
    if not day_entry:
        return None
    if isinstance(day_entry, dict):
        return {
            "start": day_entry.get("start") or day_entry.get("startTime"),
            "end": day_entry.get("end") or day_entry.get("endTime"),
        }
    # List-of-intervals shape.
    if isinstance(day_entry, list) and day_entry:
        first = day_entry[0]
        if isinstance(first, dict):
            return {
                "start": first.get("start") or first.get("startTime"),
                "end": first.get("end") or first.get("endTime"),
            }
    return None


def _task_counts(tasks: Any, now_local: datetime) -> dict[str, int]:
    """Summarize a task list into counts Claude typically wants at a glance."""
    if not isinstance(tasks, list):
        return {"total": 0, "due_today": 0, "overdue": 0, "in_progress": 0, "unscheduled": 0}

    today = now_local.date()
    due_today = overdue = in_progress = unscheduled = 0

    for t in tasks:
        if not isinstance(t, dict):
            continue
        status = t.get("status")
        if status == "IN_PROGRESS":
            in_progress += 1
        if status == "NEW":
            unscheduled += 1
        due = t.get("due")
        if isinstance(due, str) and due:
            try:
                due_dt = datetime.fromisoformat(due.replace("Z", "+00:00"))
                due_local = due_dt.astimezone(now_local.tzinfo).date()
                if due_local == today:
                    due_today += 1
                elif due_local < today and status not in ("COMPLETE", "ARCHIVED"):
                    overdue += 1
            except ValueError:
                pass

    return {
        "total": len(tasks),
        "due_today": due_today,
        "overdue": overdue,
        "in_progress": in_progress,
        "unscheduled": unscheduled,
    }


def _active_timer(tasks: Any) -> Optional[dict[str, Any]]:
    """Return a compact view of the currently-running task timer, if any."""
    if not isinstance(tasks, list):
        return None
    for t in tasks:
        if isinstance(t, dict) and t.get("status") == "IN_PROGRESS":
            return {
                "task_id": t.get("id"),
                "title": t.get("title"),
                "minutes_worked": (t.get("timeChunksSpent") or 0) * 15,
                "minutes_total": (t.get("timeChunksRequired") or 0) * 15,
            }
    return None


@ttl_cache(ttl=30)
async def get_context() -> dict[str, Any]:
    """Anchor the current user/time context for any scheduling flow.

    Returns:
        {
          "now": ISO datetime with offset,
          "timezone": IANA zone (e.g., 'America/Los_Angeles'),
          "weekday": weekday name,
          "working_hours_today": {start, end} or null,
          "current_moment": what the user is doing right now,
          "next_moment": what's coming up next,
          "active_timer": running task timer info, or null,
          "task_counts": {total, due_today, overdue, in_progress, unscheduled},
        }
    """
    settings = get_settings()
    client = _get_client()

    try:
        results = await asyncio.gather(
            client.get("/api/timeschemes"),
            client.get("/api/moment"),
            client.get("/api/moment/next"),
            client.get("/api/tasks", params={"status": "NEW,SCHEDULED,IN_PROGRESS"}),
            return_exceptions=True,
        )
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error getting context: {e}")

    timeschemes, current_moment, next_moment, tasks = results

    # Resolve timezone: env override > Reclaim > system > UTC.
    tz_name = settings.timezone
    if not tz_name and not isinstance(timeschemes, Exception):
        tz_name = _extract_tz_from_timeschemes(timeschemes)
    if not tz_name:
        tz_name = _system_tz()
    try:
        zone = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        tz_name = "UTC"
        zone = ZoneInfo("UTC")

    now_local = datetime.now(zone)
    weekday_name = now_local.strftime("%A").upper()

    working_hours = None
    if not isinstance(timeschemes, Exception):
        working_hours = _working_hours_for_today(timeschemes, weekday_name)

    return {
        "now": now_local.isoformat(),
        "timezone": tz_name,
        "weekday": weekday_name,
        "working_hours_today": working_hours,
        "current_moment": current_moment if not isinstance(current_moment, Exception) else None,
        "next_moment": next_moment if not isinstance(next_moment, Exception) else None,
        "active_timer": _active_timer(tasks) if not isinstance(tasks, Exception) else None,
        "task_counts": _task_counts(tasks, now_local) if not isinstance(tasks, Exception) else {},
    }
