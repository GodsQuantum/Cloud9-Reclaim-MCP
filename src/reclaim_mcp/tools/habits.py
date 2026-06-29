"""Smart habit tools."""

from __future__ import annotations

from typing import Any, Optional

from fastmcp.exceptions import ToolError
from pydantic import ValidationError

from reclaim_mcp.cache import invalidate_cache, ttl_cache
from reclaim_mcp.client import ReclaimClient
from reclaim_mcp.config import get_settings
from reclaim_mcp.exceptions import NotFoundError, RateLimitError, ReclaimError
from reclaim_mcp.models import CalendarEventId, EventInstanceId, HabitCreate, HabitId, HabitUpdate
from reclaim_mcp.responses import make_response, thin_habit
from reclaim_mcp.utils import format_validation_errors


def _get_client() -> ReclaimClient:
    return ReclaimClient(get_settings())


def _build_habit_payload(v: HabitCreate) -> dict[str, Any]:
    recurrence: dict[str, Any] = {"frequency": v.frequency.value}
    if v.ideal_days:
        recurrence["idealDays"] = [d.value for d in v.ideal_days]

    time_policy_str = (
        v.time_policy_type.value
        if v.time_policy_type is not None
        else ("PERSONAL" if v.event_type.value == "PERSONAL" else "WORK")
    )

    ideal_time = v.ideal_time if len(v.ideal_time) != 5 else f"{v.ideal_time}:00"

    payload: dict[str, Any] = {
        "title": v.title,
        "idealTime": ideal_time,
        "durationMinMins": v.duration_min_mins,
        "durationMaxMins": v.duration_max_mins or v.duration_min_mins,
        "enabled": v.enabled,
        "recurrence": recurrence,
        "organizer": {"timePolicyType": time_policy_str},
        "eventType": v.event_type.value,
        "defenseAggression": v.defense_aggression.value,
    }
    if v.description:
        payload["description"] = v.description
    return payload


@ttl_cache(ttl=120)
async def list_habits(detail: str = "thin") -> list[dict[str, Any]]:
    """List all smart habits.

    Args:
        detail: 'thin' (default) or 'full'.
    """
    try:
        client = _get_client()
        raw = await client.get("/api/smart-habits")
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error listing habits: {e}")

    if detail == "thin" and isinstance(raw, list):
        return [thin_habit(h) for h in raw]
    return raw


@ttl_cache(ttl=60)
async def get_habit(habit_id: int, detail: str = "full") -> dict[str, Any]:
    """Get one habit by its `habit_id` (what the API calls lineageId)."""
    try:
        validated = HabitId(lineage_id=habit_id)
    except ValidationError as e:
        raise ToolError(format_validation_errors(e))

    try:
        client = _get_client()
        habit = await client.get(f"/api/smart-habits/{validated.lineage_id}")
    except NotFoundError:
        raise ToolError(f"Habit {habit_id} not found")
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error getting habit {habit_id}: {e}")

    if detail == "thin":
        return thin_habit(habit)
    return habit


async def create_habit(
    title: str,
    ideal_time: str,
    duration_min_mins: int,
    frequency: str = "WEEKLY",
    ideal_days: Optional[list[str]] = None,
    event_type: str = "SOLO_WORK",
    defense_aggression: str = "DEFAULT",
    duration_max_mins: Optional[int] = None,
    description: Optional[str] = None,
    enabled: bool = True,
    time_policy_type: Optional[str] = None,
) -> dict[str, Any]:
    """Create a recurring smart habit that Reclaim auto-schedules."""
    try:
        validated = HabitCreate(
            title=title,
            ideal_time=ideal_time,
            duration_min_mins=duration_min_mins,
            duration_max_mins=duration_max_mins,
            frequency=frequency,  # type: ignore[arg-type]
            ideal_days=ideal_days,  # type: ignore[arg-type]
            event_type=event_type,  # type: ignore[arg-type]
            defense_aggression=defense_aggression,  # type: ignore[arg-type]
            description=description,
            enabled=enabled,
            time_policy_type=time_policy_type,  # type: ignore[arg-type]
        )
    except ValidationError as e:
        raise ToolError(format_validation_errors(e))

    try:
        client = _get_client()
        habit = await client.post("/api/smart-habits", data=_build_habit_payload(validated))
        invalidate_cache("list_habits")
        invalidate_cache("get_habit")
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error creating habit '{title}': {e}")

    return make_response(habit, summary=f"Created habit '{validated.title}'.")


async def update_habit(
    habit_id: int,
    title: Optional[str] = None,
    ideal_time: Optional[str] = None,
    duration_min_mins: Optional[int] = None,
    duration_max_mins: Optional[int] = None,
    enabled: Optional[bool] = None,
    frequency: Optional[str] = None,
    ideal_days: Optional[list[str]] = None,
    event_type: Optional[str] = None,
    defense_aggression: Optional[str] = None,
    description: Optional[str] = None,
) -> dict[str, Any]:
    """Update an existing habit. Omit fields to leave them unchanged."""
    try:
        validated_id = HabitId(lineage_id=habit_id)
    except ValidationError as e:
        raise ToolError(format_validation_errors(e))

    try:
        v = HabitUpdate(
            title=title,
            ideal_time=ideal_time,
            duration_min_mins=duration_min_mins,
            duration_max_mins=duration_max_mins,
            enabled=enabled,
            frequency=frequency,  # type: ignore[arg-type]
            ideal_days=ideal_days,  # type: ignore[arg-type]
            event_type=event_type,  # type: ignore[arg-type]
            defense_aggression=defense_aggression,  # type: ignore[arg-type]
            description=description,
        )
    except ValidationError as e:
        raise ToolError(format_validation_errors(e))

    payload: dict[str, Any] = {}
    if v.title is not None:
        payload["title"] = v.title
    if v.ideal_time is not None:
        ideal = v.ideal_time if len(v.ideal_time) != 5 else f"{v.ideal_time}:00"
        payload["idealTime"] = ideal
    if v.duration_min_mins is not None:
        payload["durationMinMins"] = v.duration_min_mins
    if v.duration_max_mins is not None:
        payload["durationMaxMins"] = v.duration_max_mins
    if v.enabled is not None:
        payload["enabled"] = v.enabled
    if v.description is not None:
        payload["description"] = v.description
    if v.event_type is not None:
        payload["eventType"] = v.event_type.value
    if v.defense_aggression is not None:
        payload["defenseAggression"] = v.defense_aggression.value
    if v.frequency is not None or v.ideal_days is not None:
        recurrence: dict[str, Any] = {}
        if v.frequency is not None:
            recurrence["frequency"] = v.frequency.value
        if v.ideal_days is not None:
            recurrence["idealDays"] = [d.value for d in v.ideal_days]
        payload["recurrence"] = recurrence

    try:
        client = _get_client()
        habit = await client.patch(f"/api/smart-habits/{validated_id.lineage_id}", data=payload)
        invalidate_cache("list_habits")
        invalidate_cache("get_habit")
    except NotFoundError:
        raise ToolError(f"Habit {habit_id} not found")
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error updating habit {habit_id}: {e}")

    return make_response(habit, summary=f"Updated habit {habit_id}.")


async def delete_habit(habit_id: int) -> dict[str, Any]:
    """Delete a habit entirely. To pause without deleting, use `set_habit_enabled`."""
    try:
        validated = HabitId(lineage_id=habit_id)
    except ValidationError as e:
        raise ToolError(format_validation_errors(e))

    try:
        client = _get_client()
        await client.delete(f"/api/smart-habits/{validated.lineage_id}")
        invalidate_cache("list_habits")
        invalidate_cache("get_habit")
    except NotFoundError:
        raise ToolError(f"Habit {habit_id} not found")
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error deleting habit {habit_id}: {e}")

    return make_response({"deleted": True, "habit_id": habit_id}, summary=f"Deleted habit {habit_id}.")


async def set_habit_enabled(habit_id: int, enabled: bool) -> dict[str, Any]:
    """Enable or disable a habit.

    Disabled habits stay in the system but stop scheduling. Use this instead
    of `delete_habit` when you want to pause a habit.
    """
    try:
        validated = HabitId(lineage_id=habit_id)
    except ValidationError as e:
        raise ToolError(format_validation_errors(e))

    try:
        client = _get_client()
        if enabled:
            result = await client.post(f"/api/smart-habits/{validated.lineage_id}/enable", data={})
        else:
            await client.delete(f"/api/smart-habits/{validated.lineage_id}/disable")
            result = {}
        invalidate_cache("list_habits")
        invalidate_cache("get_habit")
    except NotFoundError:
        raise ToolError(f"Habit {habit_id} not found")
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        verb = "enabling" if enabled else "disabling"
        raise ToolError(f"Error {verb} habit {habit_id}: {e}")

    verb = "Enabled" if enabled else "Disabled"
    return make_response(result, summary=f"{verb} habit {habit_id}.")


async def complete_habit_instance(event_id: str) -> dict[str, Any]:
    """Mark today's habit instance as done. `event_id` comes from a personal-events listing."""
    return await _habit_instance_action(event_id, "done", "Completed")


async def skip_habit_instance(event_id: str) -> dict[str, Any]:
    """Skip today's habit instance without marking it done."""
    return await _habit_instance_action(event_id, "skip", "Skipped")


async def set_habit_instance_locked(event_id: str, locked: bool) -> dict[str, Any]:
    """Lock or unlock a single habit instance so Reclaim does (or doesn't) move it."""
    action = "lock" if locked else "unlock"
    verb = "Locked" if locked else "Unlocked"
    return await _habit_instance_action(event_id, action, verb)


async def _habit_instance_action(event_id: str, action: str, verb: str) -> dict[str, Any]:
    try:
        validated = EventInstanceId(event_id=event_id)
    except ValidationError as e:
        raise ToolError(format_validation_errors(e))

    try:
        client = _get_client()
        result = await client.post(f"/api/smart-habits/planner/{validated.event_id}/{action}", data={})
        invalidate_cache("list_habits")
        invalidate_cache("get_habit")
    except NotFoundError:
        raise ToolError(f"Habit event {event_id} not found")
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error on habit instance {event_id}: {e}")

    return make_response(result, summary=f"{verb} habit instance {event_id}.")


async def start_habit(habit_id: int) -> dict[str, Any]:
    """Start the timer on this habit right now."""
    return await _habit_timer(habit_id, "start", "Started")


async def stop_habit(habit_id: int) -> dict[str, Any]:
    """Stop a running habit timer."""
    return await _habit_timer(habit_id, "stop", "Stopped")


async def _habit_timer(habit_id: int, action: str, verb: str) -> dict[str, Any]:
    try:
        validated = HabitId(lineage_id=habit_id)
    except ValidationError as e:
        raise ToolError(format_validation_errors(e))

    try:
        client = _get_client()
        result = await client.post(f"/api/smart-habits/planner/{validated.lineage_id}/{action}", data={})
        invalidate_cache("list_habits")
        invalidate_cache("get_habit")
    except NotFoundError:
        raise ToolError(f"Habit {habit_id} not found")
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error {action}ing habit {habit_id}: {e}")

    return make_response(result, summary=f"{verb} habit {habit_id}.")


async def convert_event_to_habit(
    calendar_id: int,
    event_id: str,
    title: str,
    ideal_time: str,
    duration_min_mins: int,
    frequency: str = "WEEKLY",
    ideal_days: Optional[list[str]] = None,
    event_type: str = "SOLO_WORK",
    defense_aggression: str = "DEFAULT",
    duration_max_mins: Optional[int] = None,
    description: Optional[str] = None,
    enabled: bool = True,
    time_policy_type: Optional[str] = None,
) -> dict[str, Any]:
    """Convert a calendar event into a recurring habit.

    Doesn't work for recurring instances, all-day events, or multi-day events.
    """
    try:
        validated_event = CalendarEventId(calendar_id=calendar_id, event_id=event_id)
    except ValidationError as e:
        raise ToolError(format_validation_errors(e))

    try:
        v = HabitCreate(
            title=title,
            ideal_time=ideal_time,
            duration_min_mins=duration_min_mins,
            duration_max_mins=duration_max_mins,
            frequency=frequency,  # type: ignore[arg-type]
            ideal_days=ideal_days,  # type: ignore[arg-type]
            event_type=event_type,  # type: ignore[arg-type]
            defense_aggression=defense_aggression,  # type: ignore[arg-type]
            description=description,
            enabled=enabled,
            time_policy_type=time_policy_type,  # type: ignore[arg-type]
        )
    except ValidationError as e:
        raise ToolError(format_validation_errors(e))

    try:
        client = _get_client()
        habit = await client.post(
            f"/api/smart-habits/convert/{validated_event.calendar_id}/{validated_event.event_id}",
            data=_build_habit_payload(v),
        )
        invalidate_cache("list_habits")
        invalidate_cache("get_habit")
    except NotFoundError:
        raise ToolError(f"Event {event_id} not found in calendar {calendar_id}")
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error converting event to habit: {e}")

    return make_response(habit, summary=f"Converted event {event_id} into habit '{title}'.")
