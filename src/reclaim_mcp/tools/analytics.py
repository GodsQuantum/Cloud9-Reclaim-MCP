"""Analytics tools."""

from __future__ import annotations

from typing import Any

from fastmcp.exceptions import ToolError

from reclaim_mcp.cache import ttl_cache
from reclaim_mcp.client import ReclaimClient
from reclaim_mcp.config import get_settings
from reclaim_mcp.exceptions import RateLimitError, ReclaimError
from reclaim_mcp.time import TimeParseError, parse_range
from reclaim_mcp.user_tz import get_user_tz


def _get_client() -> ReclaimClient:
    return ReclaimClient(get_settings())


_METRICS = {"DURATION_BY_CATEGORY", "DURATION_BY_DATE_BY_CATEGORY"}


@ttl_cache(ttl=300)
async def get_user_analytics(when: str, metric_name: str) -> dict[str, Any]:
    """Productivity breakdown for a time range.

    `when` accepts NL ranges ('this week', 'last month', 'next 7 days') or
    explicit 'YYYY-MM-DD..YYYY-MM-DD'.
    `metric_name` must be one of: DURATION_BY_CATEGORY, DURATION_BY_DATE_BY_CATEGORY.
    """
    if metric_name not in _METRICS:
        raise ToolError(f"metric_name must be one of: {sorted(_METRICS)}. Got {metric_name!r}.")

    tz = await get_user_tz()
    try:
        start, end = parse_range(when, tz=tz)
    except TimeParseError as e:
        raise ToolError(str(e))

    try:
        client = _get_client()
        return await client.get(
            "/api/analytics/user/V3",
            params={"start": start, "end": end, "metricName": metric_name},
        )
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error getting user analytics: {e}")


@ttl_cache(ttl=300)
async def get_focus_insights(when: str) -> dict[str, Any]:
    """Focus-time analytics (protected hours, interruptions, recommendations).

    `when` accepts NL ranges or 'YYYY-MM-DD..YYYY-MM-DD'.
    """
    tz = await get_user_tz()
    try:
        start, end = parse_range(when, tz=tz)
    except TimeParseError as e:
        raise ToolError(str(e))

    try:
        client = _get_client()
        return await client.get("/api/analytics/focus/insights/V3", params={"start": start, "end": end})
    except RateLimitError as e:
        raise ToolError(str(e))
    except ReclaimError as e:
        raise ToolError(f"Error getting focus insights: {e}")
