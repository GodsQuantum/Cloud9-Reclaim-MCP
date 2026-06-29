"""Focus-time tools."""

from __future__ import annotations

from typing import Any, Optional

from fastmcp.exceptions import ToolError
from pydantic import ValidationError

from reclaim_mcp.cache import invalidate_cache, ttl_cache
from reclaim_mcp.client import ReclaimClient
from reclaim_mcp.config import get_settings
from reclaim_mcp.exceptions import NotFoundError, RateLimitError, ReclaimError
from reclaim_mcp.models import CalendarEventId, FocusSettingsUpdate
from reclaim_mcp.responses import make_response
from reclaim_mcp.time import TimeParseError, parse_when
from reclaim_mcp.user_tz import get_user_tz
from reclaim_mcp.utils import format_validation_errors


def _get_client() -> ReclaimClient:
    return ReclaimClient(get_settings())


@ttl_cache(ttl=120)
async def get_focus_settings() -> list[dict[str, Any]]:
    """Get the user's focus-time configuration."""
    try:
        client = _get_client()
        return await client.get("/api/focus-settings/user")
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error getting focus settings: {e}")


async def update_focus_settings(
    settings_id: int,
    min_duration_mins: Optional[int] = None,
    ideal_duration_mins: Optional[int] = None,
    max_duration_mins: Optional[int] = None,
    defense_aggression: Optional[str] = None,
    enabled: Optional[bool] = None,
) -> dict[str, Any]:
    """Update focus-time settings (durations, defense, enabled)."""
    try:
        validated = FocusSettingsUpdate(
            min_duration_mins=min_duration_mins,
            ideal_duration_mins=ideal_duration_mins,
            max_duration_mins=max_duration_mins,
            defense_aggression=defense_aggression,  # type: ignore[arg-type]
            enabled=enabled,
        )
    except ValidationError as e:
        raise ToolError(format_validation_errors(e))

    payload: dict[str, Any] = {}
    if validated.min_duration_mins is not None:
        payload["minDurationMins"] = validated.min_duration_mins
    if validated.ideal_duration_mins is not None:
        payload["idealDurationMins"] = validated.ideal_duration_mins
    if validated.max_duration_mins is not None:
        payload["maxDurationMins"] = validated.max_duration_mins
    if validated.defense_aggression is not None:
        payload["defenseAggression"] = validated.defense_aggression.value
    if validated.enabled is not None:
        payload["enabled"] = validated.enabled

    try:
        client = _get_client()
        result = await client.patch(f"/api/focus-settings/user/{settings_id}", payload)
        invalidate_cache("get_focus_settings")
    except NotFoundError:
        raise ToolError(f"Focus settings {settings_id} not found")
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error updating focus settings: {e}")

    return make_response(result, summary="Focus settings updated.")


async def set_focus_block_locked(
    calendar_id: int,
    event_id: str,
    locked: bool,
) -> dict[str, Any]:
    """Lock or unlock a focus block so Reclaim does (or doesn't) reschedule it."""
    try:
        validated = CalendarEventId(calendar_id=calendar_id, event_id=event_id)
    except ValidationError as e:
        raise ToolError(format_validation_errors(e))

    action = "lock" if locked else "unlock"
    try:
        client = _get_client()
        result = await client.post(
            f"/api/focus/planner/{validated.calendar_id}/{validated.event_id}/{action}",
            {},
        )
        invalidate_cache("list_events")
    except NotFoundError:
        raise ToolError(f"Focus block {event_id} not found in calendar {calendar_id}")
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error {action}ing focus block: {e}")

    verb = "Locked" if locked else "Unlocked"
    return make_response(result, summary=f"{verb} focus block {event_id}.")


async def reschedule_focus_block(
    calendar_id: int,
    event_id: str,
    start_at: Optional[str] = None,
    end_at: Optional[str] = None,
) -> dict[str, Any]:
    """Reschedule a focus block to a specific time, or let Reclaim pick.

    Leaving both `start_at` and `end_at` empty asks Reclaim to find a new
    slot automatically. Supplying both pins it.
    """
    tz = await get_user_tz()
    try:
        validated = CalendarEventId(calendar_id=calendar_id, event_id=event_id)
    except ValidationError as e:
        raise ToolError(format_validation_errors(e))

    resolved: dict[str, str] = {}
    payload: dict[str, str] = {}

    try:
        if start_at is not None:
            s = parse_when(start_at, tz=tz)
            payload["start"] = s.iso_utc
            resolved["start_at"] = s.iso
        if end_at is not None:
            e = parse_when(end_at, tz=tz)
            payload["end"] = e.iso_utc
            resolved["end_at"] = e.iso
    except TimeParseError as err:
        raise ToolError(str(err))

    try:
        client = _get_client()
        result = await client.post(
            f"/api/focus/planner/{validated.calendar_id}/{validated.event_id}/reschedule",
            payload,
        )
        invalidate_cache("list_events")
    except NotFoundError:
        raise ToolError(f"Focus block {event_id} not found in calendar {calendar_id}")
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error rescheduling focus block: {e}")

    summary = f"Rescheduled focus block to {resolved.get('start_at', 'a new time chosen by Reclaim')}."
    return make_response(result, summary=summary, resolved=resolved or None)
