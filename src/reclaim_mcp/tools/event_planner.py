"""Event planner tools — pin, unpin, categorize, and bulk-control events.

These are control-plane operations on calendar events that already exist:
pinning prevents Reclaim's solver from moving them, categorizing tags them
for analytics, and the bulk endpoints let you reschedule many tasks at once.
"""

from typing import Any, Optional

from fastmcp.exceptions import ToolError

from reclaim_mcp.client import ReclaimClient
from reclaim_mcp.config import get_settings
from reclaim_mcp.exceptions import RateLimitError, ReclaimError


def _get_client() -> ReclaimClient:
    settings = get_settings()
    return ReclaimClient(settings)


async def pin_event(calendar_id: int, event_id: str) -> dict:
    """Pin a calendar event so Reclaim's solver won't move it."""
    try:
        client = _get_client()
        return await client.post(
            f"/api/planner/event/{calendar_id}/{event_id}/pin", data={}
        )
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error pinning event: {e}")


async def unpin_event(calendar_id: int, event_id: str) -> dict:
    """Unpin a previously-pinned event so the solver may reschedule it."""
    try:
        client = _get_client()
        return await client.post(
            f"/api/planner/event/{calendar_id}/{event_id}/unpin", data={}
        )
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error unpinning event: {e}")


async def categorize_event(
    calendar_id: int,
    event_id: str,
    category: str,
) -> dict:
    """Tag a calendar event with a Reclaim category (e.g. WORK, PERSONAL).

    Used for analytics breakdowns and for routing into the right time policy.
    """
    payload: dict[str, Any] = {"category": category}
    try:
        client = _get_client()
        return await client.post(
            f"/api/planner/event/category/{calendar_id}/{event_id}",
            data=payload,
        )
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error categorizing event: {e}")


async def bulk_reschedule_tasks(
    task_ids: list[int],
    after: Optional[str] = None,
) -> dict:
    """Reschedule many tasks at once.

    Args:
        task_ids: List of task ids to reschedule.
        after: Optional ISO 8601 timestamp — only reschedule slots that fall
            after this moment. Omit to let the solver reschedule any time.
    """
    if not task_ids:
        raise ToolError("task_ids cannot be empty")
    payload: dict[str, Any] = {"taskIds": task_ids}
    if after is not None:
        payload["after"] = after
    try:
        client = _get_client()
        return await client.post("/api/planner/task/reschedule/bulk", data=payload)
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error bulk-rescheduling tasks: {e}")
