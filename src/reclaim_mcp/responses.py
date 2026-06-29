"""Response envelopes for mutation tools.

Reads (list_*, get_*) return raw data for minimal overhead. Mutations and any
tool that resolves user-supplied time return an envelope with:

  - `data`: the underlying API object, so chained tools can use it
  - `summary`: a short human-readable sentence Claude can paraphrase
  - `resolved` (optional): echoes back any parsed time values so Claude can
    confirm to the user ("I scheduled it for Monday April 20 at 9am — OK?")
  - `warnings` (optional): soft signals the caller should surface

The envelope is a plain dict so FastMCP serializes it cleanly.
"""

from __future__ import annotations

from typing import Any, Optional


def make_response(
    data: Any,
    summary: str,
    *,
    resolved: Optional[dict[str, Any]] = None,
    warnings: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Build a mutation-tool response envelope.

    Args:
        data: The primary result (task object, event object, etc.).
        summary: One short sentence describing what happened. Keep it
            specific — "Snoozed 'Draft plan' until Monday April 20 at 9am"
            beats "Task snoozed successfully."
        resolved: Map of user-input-field -> resolved value. Used for NL
            time inputs so the user can confirm the parsed result.
        warnings: Non-fatal messages. Stale cache notes, soft conflicts.

    Returns:
        Dict with keys: data, summary, and optionally resolved/warnings.
    """
    envelope: dict[str, Any] = {"data": data, "summary": summary}
    if resolved:
        envelope["resolved"] = resolved
    if warnings:
        envelope["warnings"] = warnings
    return envelope


# --- Thin projectors for list outputs ---
# Reclaim API responses are chatty (40+ fields per task). For list views Claude
# usually only needs a handful. These projectors pull out the useful fields and
# drop the rest to keep token use low. Callers opt in via a `detail="thin"`
# param; `detail="full"` returns the raw API object.


def thin_task(task: dict[str, Any]) -> dict[str, Any]:
    """Project a task to the fields Claude typically needs."""
    chunks = task.get("timeChunksRequired", 0)
    spent = task.get("timeChunksSpent", 0)
    return {
        "id": task.get("id"),
        "title": task.get("title"),
        "status": task.get("status"),
        "priority": task.get("priority"),
        "duration_minutes": chunks * 15,
        "minutes_worked": spent * 15,
        "due": task.get("due"),
        "snooze_until": task.get("snoozeUntil"),
        "notes": task.get("notes"),
    }


def thin_event(event: dict[str, Any]) -> dict[str, Any]:
    """Project a calendar event to the fields Claude typically needs."""
    return {
        "event_id": event.get("eventId") or event.get("id"),
        "calendar_id": event.get("calendarId"),
        "title": event.get("title"),
        "start": event.get("eventStart") or event.get("start"),
        "end": event.get("eventEnd") or event.get("end"),
        "type": event.get("type") or event.get("eventType"),
        "rsvp": event.get("rsvpStatus") or event.get("responseStatus"),
    }


def thin_habit(habit: dict[str, Any]) -> dict[str, Any]:
    """Project a habit to the fields Claude typically needs."""
    recurrence = habit.get("recurrence") or {}
    return {
        "habit_id": habit.get("lineageId") or habit.get("id"),
        "title": habit.get("title"),
        "enabled": habit.get("enabled"),
        "ideal_time": habit.get("idealTime"),
        "duration_min_mins": habit.get("durationMinMins"),
        "duration_max_mins": habit.get("durationMaxMins"),
        "frequency": recurrence.get("frequency"),
        "ideal_days": recurrence.get("idealDays"),
        "defense_aggression": habit.get("defenseAggression"),
    }
