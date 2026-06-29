"""Scheduling tools — working hours and mutual availability."""

from __future__ import annotations

from typing import Any, Optional

from fastmcp.exceptions import ToolError
from pydantic import ValidationError

from reclaim_mcp.cache import ttl_cache
from reclaim_mcp.client import ReclaimClient
from reclaim_mcp.config import get_settings
from reclaim_mcp.exceptions import RateLimitError, ReclaimError
from reclaim_mcp.models import SuggestedTimesRequest
from reclaim_mcp.time import TimeParseError, parse_range
from reclaim_mcp.user_tz import get_user_tz
from reclaim_mcp.utils import format_validation_errors


def _get_client() -> ReclaimClient:
    return ReclaimClient(get_settings())


@ttl_cache(ttl=300)
async def get_working_hours() -> list[dict[str, Any]]:
    """Return the user's time-scheme definitions (one per schedule policy).

    For today's working hours specifically, prefer `get_context`.
    """
    try:
        client = _get_client()
        return await client.get("/api/timeschemes")
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error getting working hours: {e}")


async def find_available_times(
    attendees: list[str],
    duration_minutes: int,
    when: Optional[str] = None,
    limit: Optional[int] = None,
) -> dict[str, Any]:
    """Find mutual availability across attendees.

    `attendees` is a list of email addresses. `when` accepts NL ranges or
    'YYYY-MM-DD..YYYY-MM-DD'; omit to let Reclaim pick a default window.
    """
    start_date = end_date = None
    if when:
        tz = await get_user_tz()
        try:
            start_date, end_date = parse_range(when, tz=tz)
        except TimeParseError as e:
            raise ToolError(str(e))

    try:
        validated = SuggestedTimesRequest(
            attendees=attendees,
            duration_minutes=duration_minutes,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
        )
    except ValidationError as e:
        raise ToolError(format_validation_errors(e))

    payload: dict[str, Any] = {
        "attendees": validated.attendees,
        "durationMinutes": validated.duration_minutes,
    }
    if validated.start_date and validated.end_date:
        payload["scheduleWindow"] = {
            "start": validated.start_date,
            "end": validated.end_date,
        }
    if validated.limit is not None:
        payload["limit"] = validated.limit

    try:
        client = _get_client()
        return await client.post("/api/availability/suggested-times", data=payload)
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error finding available times: {e}")
