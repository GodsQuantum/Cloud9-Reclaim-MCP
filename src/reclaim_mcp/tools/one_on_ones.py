"""One-on-One meeting tools — manage recurring 1:1s with collaborators.

Reclaim's /api/oneOnOne endpoints expose recurring 1:1 meetings: list/create/
update/delete the meeting series, list scheduled instances, and use the
planner subroutes to reschedule or skip a single instance.
"""

from typing import Any, Optional

from fastmcp.exceptions import ToolError

from reclaim_mcp.cache import ttl_cache
from reclaim_mcp.client import ReclaimClient
from reclaim_mcp.config import get_settings
from reclaim_mcp.exceptions import RateLimitError, ReclaimError


def _get_client() -> ReclaimClient:
    settings = get_settings()
    return ReclaimClient(settings)


def _strip_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in payload.items() if v is not None}


@ttl_cache(ttl=60)
async def list_one_on_ones(include_instances: bool = False) -> list[dict]:
    """List recurring 1:1 meeting series.

    Args:
        include_instances: When True, embed scheduled instance details in
            each row. Default False for a lighter payload.
    """
    try:
        client = _get_client()
        params = {"instances": "true"} if include_instances else None
        return await client.get("/api/oneOnOne", params=params)
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error listing one-on-ones: {e}")


async def get_one_on_one(one_on_one_id: int) -> dict:
    """Get a single 1:1 series by id."""
    try:
        client = _get_client()
        return await client.get(f"/api/oneOnOne/{one_on_one_id}")
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error getting one-on-one {one_on_one_id}: {e}")


async def create_one_on_one(
    title: str,
    invitee_email: str,
    duration_minutes: int = 30,
    recurrence: Optional[str] = "WEEKLY",
    ideal_time: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict:
    """Create a new recurring 1:1 meeting series.

    Args:
        title: Meeting title.
        invitee_email: Email of the person you'll meet with.
        duration_minutes: Meeting duration in minutes (default 30).
        recurrence: Meeting cadence: WEEKLY (default), BIWEEKLY, MONTHLY.
        ideal_time: Preferred time of day as HH:MM (24h), optional.
        notes: Optional agenda / description.
    """
    payload = _strip_none({
        "title": title,
        "inviteeEmail": invitee_email,
        "durationMinutes": duration_minutes,
        "recurrence": recurrence,
        "idealTime": ideal_time,
        "notes": notes,
    })
    try:
        client = _get_client()
        return await client.post("/api/oneOnOne", data=payload)
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error creating one-on-one: {e}")


async def update_one_on_one(
    one_on_one_id: int,
    title: Optional[str] = None,
    duration_minutes: Optional[int] = None,
    recurrence: Optional[str] = None,
    ideal_time: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict:
    """Update properties on a 1:1 meeting series."""
    payload = _strip_none({
        "title": title,
        "durationMinutes": duration_minutes,
        "recurrence": recurrence,
        "idealTime": ideal_time,
        "notes": notes,
    })
    if not payload:
        raise ToolError("No fields to update")
    try:
        client = _get_client()
        return await client.patch(f"/api/oneOnOne/{one_on_one_id}", data=payload)
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error updating one-on-one {one_on_one_id}: {e}")


async def delete_one_on_one(one_on_one_id: int) -> bool:
    """Delete a recurring 1:1 series."""
    try:
        client = _get_client()
        return await client.delete(f"/api/oneOnOne/{one_on_one_id}")
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error deleting one-on-one {one_on_one_id}: {e}")


async def list_one_on_one_instances(one_on_one_id: int) -> list[dict]:
    """List scheduled calendar instances of a 1:1 series."""
    try:
        client = _get_client()
        return await client.get(f"/api/oneOnOne/{one_on_one_id}/instances")
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error listing instances for {one_on_one_id}: {e}")


async def reschedule_one_on_one(
    one_on_one_id: int,
    event_id: str,
    new_start: Optional[str] = None,
) -> dict:
    """Reschedule a single 1:1 instance.

    Args:
        one_on_one_id: Series id.
        event_id: Specific event id of the instance.
        new_start: Optional ISO 8601 start time. Omit to let the solver pick.
    """
    payload = _strip_none({"start": new_start})
    try:
        client = _get_client()
        return await client.post(
            f"/api/planner/one-on-one/reschedule/{one_on_one_id}/{event_id}",
            data=payload,
        )
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error rescheduling 1:1 instance: {e}")


async def skip_one_on_one_day(one_on_one_id: int, event_id: str) -> dict:
    """Skip a single day of a 1:1 (cancels that one instance)."""
    try:
        client = _get_client()
        return await client.post(
            f"/api/planner/one-on-one/skip-day/{one_on_one_id}/{event_id}",
            data={},
        )
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error skipping 1:1 day: {e}")


async def skip_one_on_one_week(one_on_one_id: int, event_id: str) -> dict:
    """Skip a whole week of a 1:1 (cancels that week's instance)."""
    try:
        client = _get_client()
        return await client.post(
            f"/api/planner/one-on-one/skip-week/{one_on_one_id}/{event_id}",
            data={},
        )
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error skipping 1:1 week: {e}")


@ttl_cache(ttl=60)
async def list_one_on_one_invites() -> list[dict]:
    """List pending 1:1 invitations sent by the user."""
    try:
        client = _get_client()
        return await client.get("/api/oneOnOne/invites")
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error listing 1:1 invites: {e}")


@ttl_cache(ttl=120)
async def get_one_on_one_suggestions() -> list[dict]:
    """Get auto-detected suggestions for new 1:1s based on past meetings."""
    try:
        client = _get_client()
        return await client.get("/api/oneOnOne/suggestions")
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error getting 1:1 suggestions: {e}")
