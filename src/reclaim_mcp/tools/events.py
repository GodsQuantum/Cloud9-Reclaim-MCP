"""Calendar event tools."""

from __future__ import annotations

from typing import Any, Optional

from fastmcp.exceptions import ToolError
from pydantic import ValidationError

from reclaim_mcp.cache import invalidate_cache, ttl_cache
from reclaim_mcp.client import ReclaimClient
from reclaim_mcp.config import get_settings
from reclaim_mcp.exceptions import NotFoundError, RateLimitError, ReclaimError
from reclaim_mcp.models import CalendarEventId, EventRsvp, ListLimit
from reclaim_mcp.responses import make_response, thin_event
from reclaim_mcp.time import TimeParseError, parse_range, parse_when
from reclaim_mcp.user_tz import get_user_tz
from reclaim_mcp.utils import format_validation_errors


def _get_client() -> ReclaimClient:
    return ReclaimClient(get_settings())


@ttl_cache(ttl=60)
async def list_events(
    when: str = "this week",
    scope: str = "all",
    calendar_ids: Optional[list[int]] = None,
    limit: int = 50,
    detail: str = "thin",
) -> list[dict[str, Any]]:
    """List calendar events in a time range.

    `when` accepts 'today', 'tomorrow', 'this week', 'next week', 'this month',
    'next 7 days', explicit range ('2026-04-20..2026-04-25'), or a single date.
    `scope` is 'external' (your calendar sources), 'personal' (Reclaim-managed
    tasks/habits/focus), or 'all' (both).
    """
    try:
        ListLimit(limit=limit)
    except ValidationError as e:
        raise ToolError(format_validation_errors(e))

    if scope not in {"all", "external", "personal"}:
        raise ToolError("scope must be one of: 'all', 'external', 'personal'")

    tz = await get_user_tz()
    try:
        start_date, end_date = parse_range(when, tz=tz)
    except TimeParseError as e:
        raise ToolError(str(e))

    client = _get_client()
    results: list[dict[str, Any]] = []

    try:
        if scope in {"all", "external"}:
            params: dict[str, Any] = {"start": start_date, "end": end_date, "thin": True}
            if calendar_ids:
                params["calendarIds"] = ",".join(str(c) for c in calendar_ids)
            external = await client.get("/api/events", params=params)
            if isinstance(external, list):
                results.extend(external)

        if scope in {"all", "personal"}:
            personal = await client.get(
                "/api/events/personal",
                params={"start": start_date, "end": end_date, "limit": limit},
            )
            if isinstance(personal, list):
                results.extend(personal)
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error listing events: {e}")

    results = results[:limit]
    if detail == "thin":
        return [thin_event(e) for e in results]
    return results


async def get_event(calendar_id: int, event_id: str, detail: str = "full") -> dict[str, Any]:
    """Get a single event by calendar+event ID.

    Works best for events returned by `list_events(scope='external')`. For
    Reclaim-managed personal events, operate on them via their planner tools
    (e.g., `complete_habit_instance`) rather than fetching directly.
    """
    try:
        validated = CalendarEventId(calendar_id=calendar_id, event_id=event_id)
    except ValidationError as e:
        raise ToolError(format_validation_errors(e))

    try:
        client = _get_client()
        event = await client.get(
            f"/api/events/{validated.calendar_id}/{validated.event_id}",
            params={"thin": detail == "thin"},
        )
    except NotFoundError:
        raise ToolError(f"Event {event_id} not found in calendar {calendar_id}")
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error getting event: {e}")

    if detail == "thin":
        return thin_event(event)
    return event


async def rsvp_event(
    calendar_id: int,
    event_id: str,
    response: str,
    notify_attendees: bool = True,
) -> dict[str, Any]:
    """Set the user's RSVP on a calendar event.

    `response` must be one of: 'accepted', 'declined', 'tentative', 'needs_action'.
    `notify_attendees` controls whether other attendees get an update email.
    """
    rsvp_map = {
        "accepted": "Accepted",
        "declined": "Declined",
        "tentative": "TentativelyAccepted",
        "needs_action": "NeedsAction",
    }
    key = response.lower().replace("-", "_")
    if key not in rsvp_map:
        raise ToolError("response must be one of: accepted, declined, tentative, needs_action")

    try:
        validated = EventRsvp(
            calendar_id=calendar_id,
            event_id=event_id,
            rsvp_status=rsvp_map[key],  # type: ignore[arg-type]
        )
    except ValidationError as e:
        raise ToolError(format_validation_errors(e))

    try:
        client = _get_client()
        result = await client.put(
            f"/api/planner/event/rsvp/{validated.calendar_id}/{validated.event_id}",
            {"responseStatus": validated.rsvp_status.value, "sendUpdates": notify_attendees},
        )
        invalidate_cache("list_events")
    except NotFoundError:
        raise ToolError(f"Event {event_id} not found in calendar {calendar_id}")
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error setting RSVP: {e}")

    return make_response(
        result,
        summary=f"RSVP set to {key.replace('_', ' ')} for event {event_id}.",
    )


async def reschedule_event(
    event_id: str,
    start_at: str,
    end_at: str,
) -> dict[str, Any]:
    """Move an event to a new time.

    `start_at` and `end_at` accept natural language ('tomorrow at 3pm'),
    date+time ('2026-04-20T15:00'), or full ISO 8601.
    """
    tz = await get_user_tz()
    try:
        start = parse_when(start_at, tz=tz)
        end = parse_when(end_at, tz=tz)
    except TimeParseError as e:
        raise ToolError(str(e))

    if start.dt >= end.dt:
        raise ToolError(f"start_at ({start.label}) must be before end_at ({end.label}).")

    try:
        client = _get_client()
        result = await client.post(
            f"/api/planner/event/move/{event_id}",
            {},
            params={"start": start.iso_utc, "end": end.iso_utc},
        )
        invalidate_cache("list_events")
    except NotFoundError:
        raise ToolError(f"Event {event_id} not found")
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error rescheduling event: {e}")

    return make_response(
        result,
        summary=f"Moved event to {start.label}.",
        resolved={"start_at": start.iso, "end_at": end.iso},
    )
